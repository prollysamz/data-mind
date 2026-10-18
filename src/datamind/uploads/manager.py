"""Upload manager for user-uploaded datasets with session isolation, profiling, and deterministic drafting."""

from __future__ import annotations

import contextlib
import csv
import json
import logging
import re
import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

import duckdb
import sqlglot
import yaml

from datamind.adapters.duckdb_adapter import DuckDBAdapter
from datamind.adapters.snowflake_adapter import SnowflakeAdapter
from datamind.agent.orchestrator import AgentOrchestrator
from datamind.config import AppConfig
from datamind.guardrails.sql_guard import SQLGuard
from datamind.llm.client import LLMClient
from datamind.retrieval.sqlite_fts import SQLiteFTSRetriever
from datamind.semantic.loader import load_semantic_model
from datamind.semantic.model import SemanticModel
from datamind.uploads.formats import normalize_file
from datamind.uploads.snowflake_store import SnowflakeUploadStore, session_schema

logger = logging.getLogger(__name__)

# Configurable upload constraints
DEFAULT_MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
DEFAULT_MAX_ROWS = 2_000_000
DEFAULT_MAX_COLUMNS = 200
DEFAULT_MAX_FILES_PER_SESSION = 5
DEFAULT_MAX_CONCURRENT_SESSIONS = 10
DEFAULT_SESSION_TTL_SECONDS = 7200  # 2 hours

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
PHONE_REGEX = re.compile(r"^\+?[\d\s\-\(\)]{7,20}$")
PII_KEYWORDS = {"ssn", "social_security", "credit_card", "password", "secret", "token", "email", "phone"}


class UploadError(Exception):
    """Raised when uploaded file fails validation or ingestion."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def sanitize_identifier(raw: str, default_prefix: str = "item") -> str:
    """Sanitize arbitrary string into safe SQL identifier (lowercase snake_case)."""
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", raw.strip().lower()).strip("_")
    if not cleaned:
        cleaned = f"{default_prefix}_{uuid.uuid4().hex[:6]}"
    if cleaned[0].isdigit():
        cleaned = f"t_{cleaned}"
    return cleaned[:60]


def quote_identifier(identifier: str) -> str:
    """Return a DuckDB-safe quoted identifier."""
    return '"' + identifier.replace('"', '""') + '"'


def quote_sql_string(value: str) -> str:
    """Return a SQL string literal with embedded quotes escaped."""
    return "'" + value.replace("'", "''") + "'"


class UploadSession:
    """Represents an isolated uploaded dataset session."""

    def __init__(
        self,
        session_id: str,
        session_dir: Path,
        created_at: float,
        ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
    ) -> None:
        self.session_id = session_id
        self.session_dir = session_dir
        self.created_at = created_at
        self.ttl_seconds = ttl_seconds
        self.db_path = session_dir / "data.duckdb"
        self.semantic_path = session_dir / "semantic_model.yaml"
        self.fts_path = session_dir / "fts.sqlite"
        self.meta_path = session_dir / "session.json"
        self.status = "pending_review"  # pending_review, active, deleted
        self.tables_meta: dict[str, Any] = {}
        self.reversible_mappings: dict[str, dict[str, str]] = {}  # table -> {sanitized: original}
        self.encoding_notices: list[str] = []
        self.backend = "duckdb"

    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl_seconds

    def save_metadata(self) -> None:
        data = {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "ttl_seconds": self.ttl_seconds,
            "status": self.status,
            "tables_meta": self.tables_meta,
            "reversible_mappings": self.reversible_mappings,
            "encoding_notices": self.encoding_notices,
            "backend": self.backend,
        }
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load_metadata(self) -> None:
        if self.meta_path.exists():
            with open(self.meta_path, encoding="utf-8") as f:
                data = json.load(f)
                self.created_at = data.get("created_at", self.created_at)
                self.ttl_seconds = data.get("ttl_seconds", self.ttl_seconds)
                self.status = data.get("status", self.status)
                self.tables_meta = data.get("tables_meta", {})
                self.reversible_mappings = data.get("reversible_mappings", {})
                self.encoding_notices = data.get("encoding_notices", [])
                self.backend = data.get("backend", "duckdb")


class UploadManager:
    """Manages secure ingestion, profiling, drafting, and session lifecycle for uploads."""

    def __init__(
        self,
        base_dir: str | Path = ".datamind/uploads",
        max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
        max_rows: int = DEFAULT_MAX_ROWS,
        max_columns: int = DEFAULT_MAX_COLUMNS,
        max_files_per_session: int = DEFAULT_MAX_FILES_PER_SESSION,
        max_concurrent_sessions: int = DEFAULT_MAX_CONCURRENT_SESSIONS,
        session_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
        enabled: bool = False,
        config: AppConfig | None = None,
    ) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.max_file_size_bytes = max_file_size_bytes
        self.max_rows = max_rows
        self.max_columns = max_columns
        self.max_files_per_session = max_files_per_session
        self.max_concurrent_sessions = max_concurrent_sessions
        self.session_ttl_seconds = session_ttl_seconds
        self.enabled = enabled
        self.config = config or AppConfig()
        self.snowflake_store = SnowflakeUploadStore(self.config) if self.config.backend.type == "snowflake" else None
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._active_sessions: dict[str, UploadSession] = {}
        self.load_existing_sessions()

    def load_existing_sessions(self) -> None:
        """Load valid non-expired sessions from disk on startup."""
        for child in self.base_dir.iterdir():
            if child.is_dir() and (child / "session.json").exists():
                session = UploadSession(child.name, child, created_at=time.time())
                try:
                    session.load_metadata()
                    if not session.is_expired() and session.status != "deleted":
                        self._active_sessions[session.session_id] = session
                    else:
                        self._active_sessions[session.session_id] = session
                        self.delete_session(session.session_id)
                except Exception:
                    logger.warning("Session could not be restored or cleaned up; retaining %s for retry", child.name)

    def create_session(self) -> UploadSession:
        """Create new isolated session directory with random UUID."""
        if not self.enabled:
            raise UploadError("File uploads are disabled. Start server with --enable-uploads to enable.", 403)

        self.cleanup_expired()
        active_count = len([s for s in self._active_sessions.values() if not s.is_expired()])
        if active_count >= self.max_concurrent_sessions:
            raise UploadError(
                f"Maximum concurrent upload sessions ({self.max_concurrent_sessions}) reached. Please try again later.",
                429,
            )

        session_id = uuid.uuid4().hex[:12]
        session_dir = self.base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        session = UploadSession(
            session_id=session_id,
            session_dir=session_dir,
            created_at=time.time(),
            ttl_seconds=self.session_ttl_seconds,
        )
        session.backend = self.config.backend.type
        session.save_metadata()
        self._active_sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> UploadSession | None:
        """Retrieve session safely, checking path traversal and expiration."""
        # Sanitize session_id to alphanumeric only to prevent path traversal
        clean_id = re.sub(r"[^a-zA-Z0-9_-]", "", session_id)
        if clean_id != session_id:
            return None

        session = self._active_sessions.get(clean_id)
        if not session:
            sess_dir = self.base_dir / clean_id
            if sess_dir.exists() and (sess_dir / "session.json").exists():
                session = UploadSession(clean_id, sess_dir, created_at=time.time())
                session.load_metadata()
                self._active_sessions[clean_id] = session

        if session and session.is_expired():
            self.delete_session(session.session_id)
            return None
        return session

    def delete_session(self, session_id: str) -> bool:
        """Securely delete all files associated with a session."""
        clean_id = re.sub(r"[^a-zA-Z0-9_-]", "", session_id)
        if not clean_id or clean_id != session_id:
            return False

        sess_dir = (self.base_dir / clean_id).resolve()
        if not sess_dir.is_relative_to(self.base_dir):
            return False

        existed = clean_id in self._active_sessions or sess_dir.exists()
        session = self._active_sessions.get(clean_id)
        if session and session.backend == "snowflake":
            if not self.snowflake_store:
                raise UploadError("Reconnect using the Snowflake configuration to delete this cloud session.", 409)
            try:
                self.snowflake_store.delete_session(clean_id)
            except Exception as exc:
                logger.exception("Cloud session cleanup failed")
                raise UploadError("Snowflake deletion failed. The session was retained so deletion can be retried.", 502) from exc
        if sess_dir.exists():
            try:
                shutil.rmtree(sess_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Error deleting session dir {sess_dir}: {e}")
        if clean_id in self._active_sessions:
            del self._active_sessions[clean_id]
        return existed

    def cleanup_expired(self) -> int:
        """Remove all expired sessions."""
        removed = 0
        for sid, session in list(self._active_sessions.items()):
            if session.is_expired():
                self.delete_session(sid)
                removed += 1
        return removed

    def cleanup_all(self) -> None:
        """Remove all upload sessions (called on server shutdown)."""
        for sid in list(self._active_sessions.keys()):
            self.delete_session(sid)
        if self.base_dir.exists():
            shutil.rmtree(self.base_dir, ignore_errors=True)

    def ingest_file(
        self,
        session: UploadSession,
        filename: str,
        file_bytes: bytes,
    ) -> dict[str, Any]:
        """Ingest raw uploaded file into DuckDB with validation, profiling, and drafting."""
        if not self.enabled:
            raise UploadError("File uploads are disabled.", 403)
        if session.status != "pending_review":
            raise UploadError("Create a new session to add files after activation.", 409)
        if not isinstance(filename, str) or not filename or "\x00" in filename or len(filename) > 255:
            raise UploadError("Invalid filename: use a name under 256 characters without null bytes.", 400)

        if len(session.tables_meta) >= self.max_files_per_session:
            raise UploadError(
                f"Maximum files per session ({self.max_files_per_session}) reached.", 400
            )

        # 1. Size validation
        size_bytes = len(file_bytes)
        if size_bytes == 0:
            raise UploadError("File is empty (0 bytes).", 400)
        if size_bytes > self.max_file_size_bytes:
            max_mb = self.max_file_size_bytes / (1024 * 1024)
            actual_mb = size_bytes / (1024 * 1024)
            raise UploadError(
                f"File size ({actual_mb:.1f} MB) exceeds maximum allowed {max_mb:.1f} MB.", 400
            )

        original_filename = filename
        try:
            filename, file_bytes, notices = normalize_file(filename, file_bytes, self.max_rows, self.max_columns)
            session.encoding_notices.extend(notices)
        except Exception as exc:
            raise UploadError(f"Could not read this file: {exc}", 400) from exc

        # 2. Path traversal guard on filename
        safe_stem = Path(filename.replace("\\", "/")).stem
        sanitized_table = sanitize_identifier(safe_stem, default_prefix="tbl")

        # Deduplicate table name within session
        original_table_name = sanitized_table
        counter = 1
        while sanitized_table in session.tables_meta:
            sanitized_table = f"{original_table_name}_{counter}"
            counter += 1
        table_ident = quote_identifier(sanitized_table)

        # 3. Detect format and binary content
        is_parquet = filename.lower().endswith(".parquet") or file_bytes[:4] == b"PAR1"

        text_content: str | None = None
        encoding_notice = None

        if not is_parquet:
            # Check for binary null bytes in CSV/TSV
            if b"\x00" in file_bytes[:4096]:
                raise UploadError(
                    "Binary file content detected. Only valid CSV, TSV, or Parquet files are supported.",
                    400,
                )

            # Detect encoding
            for enc, name in [
                ("utf-8-sig", "UTF-8 with BOM"),
                ("utf-8", "UTF-8"),
                ("latin1", "Latin-1 (fallback)"),
            ]:
                try:
                    text_content = file_bytes.decode(enc)
                    if name != "UTF-8":
                        encoding_notice = f"Decoded file using {name}."
                        session.encoding_notices.append(f"{filename}: {encoding_notice}")
                    break
                except UnicodeDecodeError:
                    continue

            if text_content is None:
                raise UploadError("Unable to decode file text with UTF-8 or Latin-1.", 400)

        # Write sanitized temporary input file inside session dir
        temp_input = session.session_dir / f"input_{uuid.uuid4().hex[:8]}.{'parquet' if is_parquet else 'csv'}"
        if is_parquet:
            temp_input.write_bytes(file_bytes)
        else:
            temp_input.write_text(text_content or "", encoding="utf-8", newline="")

        # 4. Ingest into DuckDB
        conn = duckdb.connect(":memory:" if session.backend == "snowflake" else str(session.db_path))
        try:
            input_path_literal = quote_sql_string(temp_input.as_posix())
            # First, check header and sanitize column names
            if is_parquet:
                desc_df = conn.execute(f"DESCRIBE SELECT * FROM read_parquet({input_path_literal})").fetchall()
                raw_columns = [row[0] for row in desc_df]
            else:
                # Sniff CSV delimiter (skipping comments)
                non_comment_lines = [line for line in (text_content.splitlines() if text_content else []) if line.strip() and not line.strip().startswith("#")]
                sample_lines = "\n".join(non_comment_lines[:20])
                delimiter = "\t" if filename.lower().endswith(".tsv") else ","
                try:
                    sniffer = csv.Sniffer()
                    dialect = sniffer.sniff(sample_lines[:4096])
                    delimiter = dialect.delimiter
                except Exception:
                    pass

                # Read header
                first_line = non_comment_lines[0] if non_comment_lines else ""
                f_reader = csv.reader([first_line], delimiter=delimiter)
                raw_columns = next(f_reader, [])

            if not raw_columns:
                raise UploadError("Could not detect any columns in the uploaded file.", 400)

            if len(raw_columns) > self.max_columns:
                raise UploadError(
                    f"File contains {len(raw_columns)} columns, exceeding maximum {self.max_columns}.", 400
                )

            # Map and deduplicate column names
            col_mapping: dict[str, str] = {}  # sanitized -> original
            sanitized_cols: list[str] = []
            seen_cols: set[str] = set()

            for i, raw_col in enumerate(raw_columns):
                clean_col = sanitize_identifier(raw_col, default_prefix=f"col_{i+1}")
                cand = clean_col
                c_idx = 1
                while cand in seen_cols:
                    cand = f"{clean_col}_{c_idx}"
                    c_idx += 1
                seen_cols.add(cand)
                sanitized_cols.append(cand)
                col_mapping[cand] = raw_col

            session.reversible_mappings[sanitized_table] = col_mapping

            # Create table in DuckDB
            if is_parquet:
                conn.execute(
                    f"CREATE TABLE {table_ident} AS SELECT * FROM read_parquet({input_path_literal});"
                )
            else:
                try:
                    conn.execute(
                        f"CREATE TABLE {table_ident} AS SELECT * FROM read_csv({input_path_literal}, auto_detect=true, header=true);"
                    )
                except Exception:
                    try:
                        conn.execute(
                            f"CREATE TABLE {table_ident} AS SELECT * FROM read_csv({input_path_literal}, auto_detect=true, header=true, sample_size=-1);"
                        )
                    except Exception:
                        # Robust fallback for heterogeneous or mixed-format columns (e.g. mixed date formats)
                        conn.execute(
                            f"CREATE TABLE {table_ident} AS SELECT * FROM read_csv({input_path_literal}, auto_detect=true, header=true, all_varchar=true);"
                        )
                        # Refine numeric columns
                        db_cols_raw = [r[1] for r in conn.execute(f"PRAGMA table_info('{sanitized_table}')").fetchall()]
                        for c_col in db_cols_raw:
                            col_ident = quote_identifier(c_col)
                            try:
                                can_dbl = conn.execute(f"SELECT COUNT(*) FROM {table_ident} WHERE TRY_CAST({col_ident} AS DOUBLE) IS NULL AND {col_ident} IS NOT NULL;").fetchone()[0] == 0
                                if can_dbl:
                                    has_frac = conn.execute(f"SELECT COUNT(*) FROM {table_ident} WHERE TRY_CAST({col_ident} AS DOUBLE) != FLOOR(TRY_CAST({col_ident} AS DOUBLE));").fetchone()[0] > 0
                                    if has_frac:
                                        conn.execute(f"ALTER TABLE {table_ident} ALTER {col_ident} TYPE DOUBLE USING TRY_CAST({col_ident} AS DOUBLE);")
                                    else:
                                        conn.execute(f"ALTER TABLE {table_ident} ALTER {col_ident} TYPE BIGINT USING TRY_CAST({col_ident} AS BIGINT);")
                            except Exception:
                                pass

            # Rename columns to sanitized names if needed
            db_cols = [r[1] for r in conn.execute(f"PRAGMA table_info('{sanitized_table}')").fetchall()]
            for orig, clean in zip(db_cols, sanitized_cols, strict=False):
                if orig != clean:
                    with contextlib.suppress(Exception):
                        conn.execute(
                            f"ALTER TABLE {table_ident} RENAME COLUMN {quote_identifier(orig)} TO {quote_identifier(clean)};"
                        )

            # 5. Row count check
            total_rows = conn.execute(f"SELECT COUNT(*) FROM {table_ident}").fetchone()[0]
            if total_rows > self.max_rows:
                conn.execute(f"DROP TABLE {table_ident};")
                raise UploadError(
                    f"File contains {total_rows:,} rows, exceeding maximum allowed {self.max_rows:,}.", 400
                )

            # 6. Profile columns
            col_profiles = self._profile_table(conn, sanitized_table, col_mapping, total_rows)

            # 7. Generate preview rows (first 10)
            preview_query = f"SELECT * FROM {table_ident} LIMIT 10"
            preview_rows = conn.execute(preview_query).fetchall()
            preview_cols = [r[1] for r in conn.execute(f"PRAGMA table_info('{sanitized_table}')").fetchall()]

            # 8. Draft verified queries
            candidate_queries = self._draft_candidate_queries(conn, sanitized_table, col_profiles)

            table_meta = {
                "table_name": sanitized_table,
                "original_filename": Path(original_filename.replace("\\", "/")).name,
                "backend": session.backend,
                "total_rows": total_rows,
                "total_columns": len(sanitized_cols),
                "columns": col_profiles,
                "preview": {
                    "columns": preview_cols,
                    "rows": [[str(v) if v is not None else None for v in row] for row in preview_rows],
                },
                "candidate_queries": candidate_queries,
                "encoding_notice": encoding_notice,
            }

            if session.backend == "snowflake":
                if not self.snowflake_store:
                    raise UploadError("Snowflake loader is not configured; no local fallback is allowed.", 503)
                try:
                    table_meta["storage"] = self.snowflake_store.load_table(
                        session.session_id, sanitized_table, conn, col_profiles, total_rows,
                    )
                except Exception as exc:
                    logger.exception("Snowflake ingestion failed")
                    raise UploadError("Snowflake upload failed. Check loader credentials and privileges. No local dataset was activated.", 502) from exc
            session.tables_meta[sanitized_table] = table_meta
            session.save_metadata()
            return table_meta

        finally:
            conn.close()
            if temp_input.exists():
                with contextlib.suppress(Exception):
                    temp_input.unlink()

    def _profile_table(
        self,
        conn: duckdb.DuckDBPyConnection,
        table_name: str,
        col_mapping: dict[str, str],
        total_rows: int,
    ) -> list[dict[str, Any]]:
        """Profile table columns for types, nulls, distinct counts, and PII patterns."""
        cols_info = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
        profiles = []
        table_ident = quote_identifier(table_name)

        for c in cols_info:
            col_name = c[1]
            col_ident = quote_identifier(col_name)
            col_type = c[2].upper()
            orig_name = col_mapping.get(col_name, col_name)

            stats = conn.execute(f"""
                SELECT
                    COUNT({col_ident}) AS non_null_count,
                    COUNT(DISTINCT {col_ident}) AS distinct_count,
                    MIN({col_ident})::VARCHAR AS min_val,
                    MAX({col_ident})::VARCHAR AS max_val
                FROM {table_ident}
            """).fetchone()

            non_null = stats[0] if stats else 0
            null_count = total_rows - non_null
            null_rate = round(null_count / total_rows, 4) if total_rows > 0 else 0.0
            distinct_count = stats[1] if stats else 0
            min_val = stats[2] if stats else None
            max_val = stats[3] if stats else None

            # Fetch up to 3 distinct sample values
            samples = conn.execute(f"""
                SELECT DISTINCT {col_ident}::VARCHAR
                FROM {table_ident}
                WHERE {col_ident} IS NOT NULL
                LIMIT 3
            """).fetchall()
            sample_values = [str(s[0])[:100] for s in samples if s[0] is not None]

            # Semantic flags
            is_date = "DATE" in col_type or "TIME" in col_type or any(
                k in col_name for k in ("date", "month", "year", "created", "timestamp", "time")
            )
            is_currency = (
                any(k in col_name for k in ("amount", "price", "revenue", "cost", "sales", "total", "fee", "tax"))
                and any(t in col_type for t in ("DECIMAL", "DOUBLE", "FLOAT", "NUMERIC", "INT"))
            )
            is_id = (
                col_name.endswith(("_id", "id", "_no", "code", "key", "_num"))
                or (distinct_count == total_rows and total_rows > 0)
            )
            is_document = (
                ("VARCHAR" in col_type or "TEXT" in col_type)
                and (
                    any(len(s) > 30 and " " in s for s in sample_values)
                    or any(k in col_name for k in ("description", "text", "comment", "review", "notes", "ticket", "body", "complaint"))
                )
            )

            # PII heuristics
            pii_warning = None
            if any(k in col_name for k in PII_KEYWORDS):
                pii_warning = f"Column name contains sensitive keyword ('{col_name}')."
            elif sample_values and any(EMAIL_REGEX.match(s) for s in sample_values):
                pii_warning = "Email addresses detected in sample values."
            elif sample_values and any(PHONE_REGEX.match(s) for s in sample_values):
                pii_warning = "Phone numbers detected in sample values."

            profiles.append({
                "name": col_name,
                "original_name": orig_name,
                "inferred_type": col_type,
                "null_rate": null_rate,
                "distinct_count": distinct_count,
                "min": min_val,
                "max": max_val,
                "sample_values": sample_values,
                "is_date": is_date,
                "is_currency": is_currency,
                "is_id": is_id,
                "is_document": is_document,
                "pii_warning": pii_warning,
            })

        return profiles

    def _draft_candidate_queries(
        self,
        conn: duckdb.DuckDBPyConnection,
        table_name: str,
        columns: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        """Generate deterministic candidate verified queries checked against SQLGuard."""
        guard = SQLGuard(approved_tables=[table_name], dialect="duckdb")
        candidates: list[dict[str, str]] = []
        table_ident = quote_identifier(table_name)

        # 1. Total records
        cand1 = {
            "name": f"total_{table_name}_count",
            "question": f"What is the total number of records in {table_name}?",
            "sql": f"SELECT COUNT(*) AS total_count FROM {table_ident}",
        }
        candidates.append(cand1)

        # 2. Top N by metric
        num_cols = [c for c in columns if any(t in c["inferred_type"] for t in ("DECIMAL", "DOUBLE", "INT", "FLOAT", "NUMERIC")) and not c["is_id"]]
        cat_cols = [c for c in columns if ("VARCHAR" in c["inferred_type"] or "TEXT" in c["inferred_type"]) and not c["is_document"] and 1 < c["distinct_count"] <= 50]

        if num_cols and cat_cols:
            n_col = num_cols[0]["name"]
            c_col = cat_cols[0]["name"]
            n_ident = quote_identifier(n_col)
            c_ident = quote_identifier(c_col)
            cand2 = {
                "name": f"top_{c_col}_by_{n_col}",
                "question": f"Which {c_col} has the highest total {n_col}?",
                "sql": f"SELECT {c_ident}, SUM({n_ident}) AS total_{n_col} FROM {table_ident} GROUP BY {c_ident} ORDER BY total_{n_col} DESC LIMIT 5",
            }
            candidates.append(cand2)

        # 3. Time series trend if date exists
        date_cols = [c for c in columns if c["is_date"]]
        if date_cols and num_cols:
            d_col = date_cols[0]["name"]
            n_col = num_cols[0]["name"]
            d_ident = quote_identifier(d_col)
            n_ident = quote_identifier(n_col)
            cand3 = {
                "name": f"{n_col}_over_time",
                "question": f"What is the trend of {n_col} over time?",
                "sql": f"SELECT CAST({d_ident} AS DATE) AS period, SUM({n_ident}) AS total_{n_col} FROM {table_ident} WHERE {d_ident} IS NOT NULL GROUP BY period ORDER BY period LIMIT 12",
            }
            candidates.append(cand3)

        # Validate candidate queries through SQLGuard and dry-run execute
        valid_candidates = []
        for cand in candidates:
            try:
                guard.validate(cand["sql"])
                conn.execute(cand["sql"]).fetchall()
                valid_candidates.append(cand)
            except Exception as e:
                logger.debug(f"Candidate query rejected: {cand['sql']} - {e}")

        return valid_candidates

    def confirm_model(
        self,
        session: UploadSession,
        review_config: dict[str, Any],
    ) -> SemanticModel:
        """Apply user human-review edits, generate verified queries, build FTS if requested, and activate session."""
        if session.status == "deleted":
            raise UploadError("Session was deleted.", 404)

        # 1. Build semantic model dictionary
        tables_def = []
        doc_tables: list[dict[str, str]] = []

        for tbl_name, t_meta in session.tables_meta.items():
            user_tbl_cfg = review_config.get("tables", {}).get(tbl_name, {})
            tbl_desc = user_tbl_cfg.get("description", f"User-uploaded table {tbl_name} with {t_meta['total_rows']} rows.")

            cols_def = []
            for col in t_meta["columns"]:
                c_name = col["name"]
                user_col_cfg = user_tbl_cfg.get("columns", {}).get(c_name, {})

                # If user deselected column, skip
                if not user_col_cfg.get("enabled", True):
                    continue

                col_desc = user_col_cfg.get("description", f"{col['original_name']} column")
                is_doc = user_col_cfg.get("is_document", col.get("is_document", False))
                pk_flag = user_col_cfg.get("is_primary_key", col.get("is_id", False))

                cols_def.append({
                    "name": c_name.upper() if session.backend == "snowflake" else c_name,
                    "type": col["inferred_type"],
                    "description": col_desc,
                    "is_primary_key": pk_flag,
                    "is_document": is_doc,
                })

                if is_doc:
                    # Find primary key column
                    pk_col = next((c["name"] for c in t_meta["columns"] if c.get("is_id")), "rowid")
                    doc_tables.append({
                        "table": tbl_name,
                        "text_col": c_name,
                        "pk_col": pk_col,
                    })

            if not cols_def:
                raise UploadError("Keep at least one enabled column in every table.", 400)
            tables_def.append({
                "name": tbl_name.upper() if session.backend == "snowflake" else tbl_name,
                "description": tbl_desc,
                "columns": cols_def,
            })

        # Compile verified queries
        v_queries = []
        for t_meta in session.tables_meta.values():
            for cq in t_meta.get("candidate_queries", []):
                v_queries.append({
                    "name": cq["name"],
                    "question": cq["question"],
                    "sql": cq["sql"],
                })

        model_dict = {
            "name": f"uploaded_session_{session.session_id}",
            "description": f"User uploaded dataset ({', '.join(session.tables_meta.keys())})",
            "default_currency": review_config.get("default_currency", "USD"),
            "currency_symbol": review_config.get("currency_symbol", "$"),
            "tables": tables_def,
            "verified_queries": v_queries,
        }

        if session.backend == "snowflake":
            for candidate in model_dict["verified_queries"]:
                tree = sqlglot.parse_one(candidate["sql"], read="duckdb")
                for node in tree.find_all(sqlglot.exp.Identifier):
                    node.set("this", node.name.upper())
                candidate["sql"] = tree.sql(dialect="snowflake")

        review_guard = SQLGuard(
            approved_tables=[t["name"] for t in tables_def], dialect=session.backend,
            approved_columns={t["name"]: {c["name"]: "UNKNOWN" for c in t["columns"]} for t in tables_def},
        )
        safe_candidates = []
        for candidate in model_dict["verified_queries"]:
            try:
                candidate["sql"] = review_guard.validate(candidate["sql"])
                safe_candidates.append(candidate)
            except ValueError:
                continue
        model_dict["verified_queries"] = safe_candidates

        # Write semantic_model.yaml
        with open(session.semantic_path, "w", encoding="utf-8") as f:
            yaml.dump(model_dict, f, sort_keys=False)

        # 2. Build FTS5 index if document columns exist
        if session.backend == "duckdb" and doc_tables and session.db_path.exists():
            self._build_session_fts(session, doc_tables)

        session.status = "active"
        session.save_metadata()

        return load_semantic_model(str(session.semantic_path))

    def _build_session_fts(self, session: UploadSession, doc_tables: list[dict[str, str]]) -> None:
        """Index user-specified document columns into SQLite FTS5 with chunk IDs D:<table>:<pk>."""
        conn_duck = duckdb.connect(str(session.db_path), read_only=True)
        conn_sqlite = sqlite3.connect(str(session.fts_path))
        try:
            conn_sqlite.execute("DROP TABLE IF EXISTS documents_fts;")
            conn_sqlite.execute("DROP TABLE IF EXISTS documents_meta;")
            conn_sqlite.execute("""
                CREATE VIRTUAL TABLE documents_fts USING fts5(
                    chunk_id UNINDEXED,
                    table_name UNINDEXED,
                    content,
                    tokenize='porter unicode61'
                );
            """)
            conn_sqlite.execute("""
                CREATE TABLE documents_meta (
                    chunk_id TEXT PRIMARY KEY,
                    table_name TEXT,
                    raw_id TEXT,
                    content TEXT
                );
            """)

            for item in doc_tables:
                tbl = item["table"]
                text_col = item["text_col"]
                pk_col = item["pk_col"]

                pk_ident = quote_identifier(pk_col)
                text_ident = quote_identifier(text_col)
                table_ident = quote_identifier(tbl)
                query = f"SELECT {pk_ident}::VARCHAR AS pk, {text_ident}::VARCHAR AS txt FROM {table_ident} WHERE {text_ident} IS NOT NULL LIMIT 5000"
                rows = conn_duck.execute(query).fetchall()

                for row in rows:
                    pk_val = str(row[0])
                    content = str(row[1])
                    chunk_id = f"D:{tbl}:{pk_val}"

                    conn_sqlite.execute(
                        "INSERT INTO documents_fts (chunk_id, table_name, content) VALUES (?, ?, ?);",
                        (chunk_id, tbl, content),
                    )
                    conn_sqlite.execute(
                        "INSERT OR REPLACE INTO documents_meta (chunk_id, table_name, raw_id, content) VALUES (?, ?, ?, ?);",
                        (chunk_id, tbl, pk_val, content),
                    )

            conn_sqlite.commit()
        finally:
            conn_duck.close()
            conn_sqlite.close()

    def create_session_orchestrator(
        self,
        session_id: str,
        config: AppConfig,
    ) -> tuple[AgentOrchestrator, DuckDBAdapter | SnowflakeAdapter, SQLiteFTSRetriever | None]:
        """Instantiate an isolated read-only AgentOrchestrator for an active upload session."""
        session = self.get_session(session_id)
        if not session or session.status != "active":
            raise UploadError("Session not found or not active.", 404)

        semantic_model = load_semantic_model(str(session.semantic_path))

        if session.backend == "snowflake":
            if config.backend.type != "snowflake":
                raise UploadError("This dataset requires the Snowflake backend; no local fallback is allowed.", 409)
            snowflake_config = config.backend.snowflake.model_copy(update={"schema_": session_schema(session.session_id)})
            adapter = SnowflakeAdapter(config=snowflake_config, max_rows=config.guardrails.max_rows)
        else:
            if config.backend.type == "snowflake":
                raise UploadError("This is an older local upload. Re-upload it to load it into Snowflake.", 409)
            adapter = DuckDBAdapter(db_path=str(session.db_path), read_only=True, max_rows=config.guardrails.max_rows)

        retriever = None
        if session.fts_path.exists():
            retriever = SQLiteFTSRetriever(
                index_path=str(session.fts_path),
                source_db_path=str(session.db_path),
            )

        llm_client = LLMClient(config.llm)
        guard = SQLGuard(
            approved_tables=semantic_model.get_approved_table_names(), dialect=adapter.dialect,
            approved_columns={t.name: {c.name: "UNKNOWN" for c in t.columns} for t in semantic_model.tables},
        )
        orchestrator = AgentOrchestrator(
            llm_client=llm_client,
            db_adapter=adapter,
            retriever=retriever,
            semantic_model=semantic_model,
            config=config.agent,
            sql_guard=guard,
        )
        return orchestrator, adapter, retriever
