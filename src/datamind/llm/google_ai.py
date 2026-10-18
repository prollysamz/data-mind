"""Google AI Studio Gemini integration through Google's OpenAI-compatible API."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from openai import OpenAI

from datamind.config import BudgetConfig, LLMConfig
from datamind.llm.budget import CostGuard
from datamind.llm.client import LLMClient

GOOGLE_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GOOGLE_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
CACHE_TTL_SECONDS = 15 * 60
REQUEST_TIMEOUT_SECONDS = 10


class GoogleAIError(Exception):
    """Raised when Google AI cannot be reached or rejects a request."""

    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


_cache_lock = threading.Lock()
_model_cache: dict[str, dict[str, Any]] = {}


def _get_json(url: str, api_key: str) -> Any:
    request = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "DataMind",
        "x-goog-api-key": api_key,
        "x-goog-api-client": "datamind/0.1.0",
    })
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 401, 403):
            raise GoogleAIError("Google AI Studio rejected this Gemini API key.", 401) from exc
        raise GoogleAIError(f"Google AI returned HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GoogleAIError(f"Could not reach Google AI: {getattr(exc, 'reason', exc)}") from exc
    except json.JSONDecodeError as exc:
        raise GoogleAIError("Google AI returned an unreadable response.") from exc


def parse_models(payload: Any) -> list[dict[str, Any]]:
    """Reduce Google's catalogue to Gemini text-generation models suitable for chat."""
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise GoogleAIError("Google AI returned an unreadable model catalogue.")
    excluded = ("embedding", "imagen", "veo", "tts", "live", "image", "robotics", "computer-use")
    models: list[dict[str, Any]] = []
    for entry in payload["models"]:
        if not isinstance(entry, dict):
            continue
        methods = entry.get("supportedGenerationMethods") or []
        raw_name = entry.get("baseModelId") or str(entry.get("name") or "").removeprefix("models/")
        model_id = str(raw_name)
        lower_id = model_id.lower()
        if (
            not model_id.startswith("gemini-")
            or "generateContent" not in methods
            or any(part in lower_id for part in excluded)
        ):
            continue
        models.append({
            "id": model_id,
            "name": entry.get("displayName") or model_id,
            "description": entry.get("description") or "",
            "context_length": entry.get("inputTokenLimit") or 0,
            "max_completion_tokens": entry.get("outputTokenLimit") or 0,
            "supports_tools": True,
        })
    models.sort(key=lambda model: model["name"].lower())
    return models


def list_models(api_key: str, *, force: bool = False) -> list[dict[str, Any]]:
    """Return Gemini text models available to this key, with short-lived caching."""
    if not api_key:
        raise GoogleAIError("Enter a Gemini API key from Google AI Studio.", 400)
    cache_key = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    with _cache_lock:
        cached = _model_cache.get(cache_key)
        if cached and not force and time.time() - cached["at"] < CACHE_TTL_SECONDS:
            return list(cached["models"])

    entries: list[Any] = []
    page_token = ""
    while True:
        query = urllib.parse.urlencode({"pageSize": 1000, **({"pageToken": page_token} if page_token else {})})
        payload = _get_json(f"{GOOGLE_MODELS_URL}?{query}", api_key)
        if not isinstance(payload, dict):
            raise GoogleAIError("Google AI returned an unreadable model catalogue.")
        entries.extend(payload.get("models") or [])
        page_token = str(payload.get("nextPageToken") or "")
        if not page_token:
            break
    models = parse_models({"models": entries})
    if not models:
        raise GoogleAIError("This key has no compatible Gemini text models available.", 400)
    with _cache_lock:
        _model_cache[cache_key] = {"at": time.time(), "models": models}
    return list(models)


def validate_key(api_key: str) -> list[dict[str, Any]]:
    """Validate a Gemini key by listing the models it can access."""
    return list_models(api_key, force=True)


def build_client(api_key: str, model_id: str) -> LLMClient:
    """Build a DataMind client for a Gemini model selected by the user."""
    model = next((entry for entry in list_models(api_key) if entry["id"] == model_id), None)
    if model is None:
        raise GoogleAIError("This Gemini model is not available to the saved key. Choose another model.", 400)

    class _OptedInGuard(CostGuard):
        def check_cloud_allowed(self, base_url: str, *args: Any, **kwargs: Any) -> None:
            if base_url == GOOGLE_OPENAI_BASE_URL:
                return
            super().check_cloud_allowed(base_url, *args, **kwargs)

    config = LLMConfig(
        base_url=GOOGLE_OPENAI_BASE_URL,
        api_key=api_key,
        orchestrator_model=model_id,
        max_tokens=min(4096, model.get("max_completion_tokens") or 4096),
        timeout_seconds=90.0,
        budget=BudgetConfig(max_tokens_per_call=32768, max_calls_per_minute=20),
    )
    openai_client = OpenAI(
        base_url=GOOGLE_OPENAI_BASE_URL,
        api_key=api_key,
        timeout=config.timeout_seconds,
        default_headers={"x-goog-api-client": "datamind/0.1.0"},
    )
    return LLMClient(config, client=openai_client, cost_guard=_OptedInGuard(), purpose="ask")
