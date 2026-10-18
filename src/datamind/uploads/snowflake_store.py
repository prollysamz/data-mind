"""Privileged ingestion boundary. Never expose this connection as an agent tool."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from datamind.adapters.snowflake_adapter import SnowflakeAdapter
from datamind.config import AppConfig


def identifier(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError("Invalid Snowflake ingestion identifier")
    return '"' + name.upper() + '"'


def session_schema(session_id: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{12}", session_id):
        raise ValueError("Invalid upload session identifier")
    return "DATAMIND_UPLOAD_" + session_id.upper()


def snowflake_type(duck_type: str) -> str:
    kind = duck_type.upper()
    if kind.startswith(("DECIMAL", "NUMERIC")):
        match = re.fullmatch(r"(?:DECIMAL|NUMERIC)\((\d+),\s*(\d+)\)", kind)
        if match and int(match[1]) <= 38:
            return f"NUMBER({match[1]},{match[2]})"
    if "INT" in kind:
        return "NUMBER(38,0)"
    if kind in ("DOUBLE", "FLOAT", "REAL"):
        return "FLOAT"
    if kind == "BOOLEAN":
        return "BOOLEAN"
    if kind == "DATE":
        return "DATE"
    if "TIMESTAMP" in kind:
        return "TIMESTAMP_NTZ"
    return "VARCHAR"


@dataclass
class SnowflakeUploadStore:
    config: AppConfig

    def _loader(self):
        settings = self.config.uploads
        user = os.getenv(settings.loader_user_env)
        password = os.getenv(settings.loader_password_env)
        if bool(user) != bool(password):
            raise ValueError("Set both loader user and loader password, or leave both unset.")
        overrides = {"role": settings.loader_role}
        if user:
            overrides.update(user_env=settings.loader_user_env, password_env=settings.loader_password_env)
        cfg = self.config.backend.snowflake.model_copy(update=overrides)
        return SnowflakeAdapter(config=cfg)

    def load_table(self, session_id: str, table: str, local_conn, columns: list[dict], expected_rows: int) -> dict:
        schema = session_schema(session_id)
        database = self.config.backend.snowflake.database or "DATAMIND"
        namespace = f"{identifier(database)}.{identifier(schema)}"
        target = f"{namespace}.{identifier(table)}"
        role = identifier(self.config.backend.snowflake.role)
        loader = self._loader()
        cur = loader._conn.cursor()
        created = False
        try:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {namespace}")
            cur.execute(f"GRANT USAGE ON SCHEMA {namespace} TO ROLE {role}")
            definitions = ", ".join(f"{identifier(c['name'])} {snowflake_type(c['inferred_type'])}" for c in columns)
            cur.execute(f"CREATE TABLE {target} ({definitions})")
            created = True
            cur.execute("BEGIN")
            source = local_conn.execute(f'SELECT * FROM "{table}"')
            placeholders = ", ".join(["%s"] * len(columns))
            while batch := source.fetchmany(1000):
                # Values are always bound, never interpolated as SQL.
                cur.executemany(f"INSERT INTO {target} VALUES ({placeholders})", batch)
            cur.execute(f"SELECT COUNT(*) FROM {target}")
            count = int(cur.fetchone()[0])
            if count != expected_rows:
                raise ValueError("Snowflake upload row count did not match the parsed input")
            query_id = cur.sfqid
            cur.execute("COMMIT")
            cur.execute(f"GRANT SELECT ON TABLE {target} TO ROLE {role}")
            return {"backend": "snowflake", "schema": schema, "table": target, "rows": count, "query_id": query_id}
        except Exception:
            try:
                cur.execute("ROLLBACK")
                if created:
                    cur.execute(f"DROP TABLE IF EXISTS {target}")
            finally:
                raise
        finally:
            cur.close()
            loader.close()

    def delete_session(self, session_id: str) -> None:
        namespace = f"{identifier(self.config.backend.snowflake.database or 'DATAMIND')}.{identifier(session_schema(session_id))}"
        with self._loader() as loader:
            cur = loader._conn.cursor()
            try:
                cur.execute(f"DROP SCHEMA IF EXISTS {namespace} CASCADE")
            finally:
                cur.close()
