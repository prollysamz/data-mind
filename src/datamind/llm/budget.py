"""DataMind Budget and Cost Guard.

Enforces strict client-side cost controls, metering, and fail-closed cloud protection:
- Fail-closed: Cloud endpoints are refused unless DATAMIND_ALLOW_CLOUD=1 and explicit budget/prices are set.
- Local endpoints (localhost, 127.0.0.1) are free of financial charge but metered for calls and tokens.
- Persistent metering in .datamind/usage.json.
- Pre-request limit enforcement (max_usd_total, max_usd_per_run, max_calls_per_run, max_tokens_per_call, max_calls_per_minute).
- No silent retries after BudgetExceeded.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Sequence
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class BudgetConfigError(Exception):
    """Raised when cloud configuration or pricing is missing or invalid."""


class BudgetExceeded(Exception):
    """Raised when a proposed LLM call would exceed a configured budget limit."""


@dataclass
class CallRecord:
    timestamp: str
    model: str
    endpoint_host: str
    prompt_tokens: int
    completion_tokens: int
    estimated_usd: float
    is_estimated: bool = False
    purpose: str = "ask"  # ask, eval, init, upload_init
    cached: bool = False


@dataclass
class UsageSummary:
    total_usd: float = 0.0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_calls: int = 0
    remaining_budget_usd: float | None = None
    by_day: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_model: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_purpose: dict[str, dict[str, Any]] = field(default_factory=dict)


class LLMResponseCache:
    """Persistent SQLite response cache for evaluation and repeat queries."""

    def __init__(self, db_path: str | Path = ".datamind/llm_cache.sqlite") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS response_cache (
                    cache_key TEXT PRIMARY KEY,
                    model TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()

    @staticmethod
    def compute_key(
        model: str,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 8192,
    ) -> str:
        payload = {
            "model": model,
            "messages": list(messages),
            "tools": list(tools) if tools else None,
            "temperature": round(float(temperature), 3),
            "max_tokens": max_tokens,
        }
        dumped = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(dumped.encode("utf-8")).hexdigest()

    def get(self, cache_key: str) -> dict[str, Any] | None:
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT response_json FROM response_cache WHERE cache_key = ?", (cache_key,))
            row = cursor.fetchone()
            if row:
                try:
                    return json.loads(row[0])
                except Exception:
                    return None
        return None

    def set(self, cache_key: str, model: str, response_data: dict[str, Any]) -> None:
        serialized = json.dumps(response_data, default=str)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO response_cache (cache_key, model, response_json, created_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP);
            """, (cache_key, model, serialized))
            conn.commit()

    def clear(self) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("DELETE FROM response_cache;")
            conn.commit()


class CostGuard:
    """Enforces budgets, verifies cloud permissions, and meters LLM token usage."""

    def __init__(
        self,
        usage_file: str | Path = ".datamind/usage.json",
        cache_db: str | Path = ".datamind/llm_cache.sqlite",
    ) -> None:
        self.usage_file = Path(usage_file)
        self.usage_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache = LLMResponseCache(cache_db)

        # In-memory session tracking for run-level limits
        self.session_calls: int = 0
        self.session_usd: float = 0.0
        self.recent_call_timestamps: list[float] = []

    @staticmethod
    def is_local_endpoint(base_url: str) -> bool:
        """Determine whether endpoint is a local offline instance."""
        if not base_url:
            return True
        parsed = urlparse(base_url)
        hostname = (parsed.hostname or "").lower()
        return hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1")

    def check_cloud_allowed(
        self,
        base_url: str,
        max_usd_total: float | None = None,
        price_per_million_input_usd: float | None = None,
        price_per_million_output_usd: float | None = None,
    ) -> None:
        """Verify cloud endpoint safety preconditions or fail-closed."""
        if self.is_local_endpoint(base_url):
            return

        # 1. Environment authorization flag
        allow_cloud = os.getenv("DATAMIND_ALLOW_CLOUD", "").strip()
        if allow_cloud not in ("1", "true", "TRUE"):
            raise BudgetConfigError(
                "Cloud LLM endpoint refused: DATAMIND_ALLOW_CLOUD=1 is not set in environment. "
                "Cloud model calls require explicit opt-in to prevent accidental cloud spend."
            )

        # 2. Total USD budget requirement
        if max_usd_total is None or max_usd_total <= 0:
            raise BudgetConfigError(
                "Cloud LLM endpoint refused: llm.budget.max_usd_total is not configured. "
                "Set an explicit maximum dollar ceiling (e.g. 10.00) in datamind.yaml."
            )

        # 3. Explicit unit pricing requirement (no hardcoded pricing)
        if price_per_million_input_usd is None or price_per_million_output_usd is None:
            raise BudgetConfigError(
                "Cloud LLM endpoint refused: llm.budget.price_per_million_input_usd and "
                "price_per_million_output_usd must be configured. Look up current pricing "
                "from your provider's official pricing page and configure them explicitly."
            )

    def calculate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        price_input_m: float | None,
        price_output_m: float | None,
    ) -> float:
        """Calculate USD cost from token counts and per-million prices."""
        p_in = (price_input_m or 0.0) / 1_000_000.0
        p_out = (price_output_m or 0.0) / 1_000_000.0
        return round((prompt_tokens * p_in) + (completion_tokens * p_out), 6)

    def check_before_call(
        self,
        base_url: str,
        estimated_prompt_tokens: int,
        max_tokens: int,
        max_usd_total: float | None = None,
        max_usd_per_run: float | None = None,
        max_calls_per_run: int | None = None,
        max_tokens_per_call: int | None = 16384,
        max_calls_per_minute: int | None = 60,
        price_per_million_input_usd: float | None = None,
        price_per_million_output_usd: float | None = None,
    ) -> None:
        """Enforce all budget and safety limits prior to sending the request."""
        # 1. Cloud fail-closed check
        self.check_cloud_allowed(
            base_url=base_url,
            max_usd_total=max_usd_total,
            price_per_million_input_usd=price_per_million_input_usd,
            price_per_million_output_usd=price_per_million_output_usd,
        )

        is_local = self.is_local_endpoint(base_url)

        # 2. Rate limit (calls per minute)
        now = time.time()
        self.recent_call_timestamps = [t for t in self.recent_call_timestamps if now - t < 60.0]
        if max_calls_per_minute and len(self.recent_call_timestamps) >= max_calls_per_minute:
            raise BudgetExceeded(
                f"Rate limit exceeded: {len(self.recent_call_timestamps)} calls in the last 60 seconds "
                f"(max allowed: {max_calls_per_minute}/min)."
            )

        # 3. Per-call token limit (worst case: prompt + max_tokens)
        worst_case_tokens = estimated_prompt_tokens + max_tokens
        if max_tokens_per_call and worst_case_tokens > max_tokens_per_call:
            raise BudgetExceeded(
                f"Token limit exceeded: Estimated call tokens ({worst_case_tokens}) exceeds "
                f"max_tokens_per_call limit ({max_tokens_per_call})."
            )

        # 4. Calls per run limit
        if max_calls_per_run and (self.session_calls + 1) > max_calls_per_run:
            raise BudgetExceeded(
                f"Run call limit exceeded: Proposed call would reach {self.session_calls + 1} calls "
                f"(max allowed per run: {max_calls_per_run})."
            )

        # 5. Financial checks (applies only to non-local endpoints)
        if not is_local:
            worst_case_cost = self.calculate_cost(
                prompt_tokens=estimated_prompt_tokens,
                completion_tokens=max_tokens,
                price_input_m=price_per_million_input_usd,
                price_output_m=price_per_million_output_usd,
            )

            # Check per-run USD cap
            if max_usd_per_run and (self.session_usd + worst_case_cost) > max_usd_per_run:
                raise BudgetExceeded(
                    f"Per-run budget exceeded: Current run spend is ${self.session_usd:.4f}. "
                    f"Proposed call worst-case cost (${worst_case_cost:.4f}) would exceed max_usd_per_run (${max_usd_per_run:.2f})."
                )

            # Check total USD budget
            summary = self.get_usage_summary(max_usd_total=max_usd_total)
            projected_total = summary.total_usd + self.session_usd + worst_case_cost
            if max_usd_total and projected_total > max_usd_total:
                raise BudgetExceeded(
                    f"Total budget exceeded: Total historical spend is ${summary.total_usd:.4f}. "
                    f"Projected total (${projected_total:.4f}) would exceed max_usd_total (${max_usd_total:.2f})."
                )

    def record_call(
        self,
        base_url: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        is_estimated: bool = False,
        price_per_million_input_usd: float | None = None,
        price_per_million_output_usd: float | None = None,
        purpose: str = "ask",
        cached: bool = False,
    ) -> CallRecord:
        """Record metered usage to session and persistent storage."""
        is_local = self.is_local_endpoint(base_url)
        cost = 0.0
        if not is_local and not cached:
            cost = self.calculate_cost(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                price_input_m=price_per_million_input_usd,
                price_output_m=price_per_million_output_usd,
            )

        # Update session counters
        if not cached:
            self.session_calls += 1
            self.session_usd += cost
            self.recent_call_timestamps.append(time.time())

        parsed = urlparse(base_url)
        host = parsed.netloc or "local"

        record = CallRecord(
            timestamp=datetime.datetime.now().isoformat(),
            model=model,
            endpoint_host=host,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_usd=cost,
            is_estimated=is_estimated,
            purpose=purpose,
            cached=cached,
        )

        self._persist_call(record)
        return record

    def _persist_call(self, record: CallRecord) -> None:
        """Append call record to .datamind/usage.json safely."""
        data = self._read_usage_data()
        data["total_usd"] = round(data.get("total_usd", 0.0) + record.estimated_usd, 6)
        data["total_prompt_tokens"] = data.get("total_prompt_tokens", 0) + record.prompt_tokens
        data["total_completion_tokens"] = data.get("total_completion_tokens", 0) + record.completion_tokens
        data["total_calls"] = data.get("total_calls", 0) + 1
        data.setdefault("calls", []).append(asdict(record))

        temp_file = self.usage_file.with_suffix(".tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            temp_file.replace(self.usage_file)
        except Exception as e:
            logger.error("Failed to persist usage record: %s", e)

    def _read_usage_data(self) -> dict[str, Any]:
        """Read existing usage data from .datamind/usage.json."""
        if not self.usage_file.exists():
            return {
                "total_usd": 0.0,
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "total_calls": 0,
                "calls": [],
            }
        try:
            with open(self.usage_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {
                "total_usd": 0.0,
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "total_calls": 0,
                "calls": [],
            }

    def get_usage_summary(self, max_usd_total: float | None = None) -> UsageSummary:
        """Compute aggregated usage totals by day, model, and purpose."""
        data = self._read_usage_data()
        total_usd = float(data.get("total_usd", 0.0))
        rem = round(max_usd_total - total_usd, 4) if max_usd_total is not None else None

        summary = UsageSummary(
            total_usd=total_usd,
            total_prompt_tokens=int(data.get("total_prompt_tokens", 0)),
            total_completion_tokens=int(data.get("total_completion_tokens", 0)),
            total_calls=int(data.get("total_calls", 0)),
            remaining_budget_usd=rem,
        )

        for c in data.get("calls", []):
            ts = c.get("timestamp", "")
            day = ts[:10] if len(ts) >= 10 else "Unknown"
            model = c.get("model", "unknown")
            purpose = c.get("purpose", "unknown")
            cost = float(c.get("estimated_usd", 0.0))
            p_tok = int(c.get("prompt_tokens", 0))
            c_tok = int(c.get("completion_tokens", 0))

            # By Day
            day_entry = summary.by_day.setdefault(day, {"calls": 0, "usd": 0.0, "tokens": 0})
            day_entry["calls"] += 1
            day_entry["usd"] = round(day_entry["usd"] + cost, 4)
            day_entry["tokens"] += (p_tok + c_tok)

            # By Model
            model_entry = summary.by_model.setdefault(model, {"calls": 0, "usd": 0.0, "tokens": 0})
            model_entry["calls"] += 1
            model_entry["usd"] = round(model_entry["usd"] + cost, 4)
            model_entry["tokens"] += (p_tok + c_tok)

            # By Purpose
            purpose_entry = summary.by_purpose.setdefault(purpose, {"calls": 0, "usd": 0.0, "tokens": 0})
            purpose_entry["calls"] += 1
            purpose_entry["usd"] = round(purpose_entry["usd"] + cost, 4)
            purpose_entry["tokens"] += (p_tok + c_tok)

        return summary

    def reset_usage(self) -> None:
        """Reset persistent usage data."""
        empty_data = {
            "total_usd": 0.0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_calls": 0,
            "calls": [],
        }
        with open(self.usage_file, "w", encoding="utf-8") as f:
            json.dump(empty_data, f, indent=2)
        self.session_calls = 0
        self.session_usd = 0.0
        self.recent_call_timestamps.clear()
