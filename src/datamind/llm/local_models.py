"""Discovery of models installed in the user's local Ollama instance."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse, urlunparse


class LocalModelError(Exception):
    """Raised when the configured local model service cannot be queried."""

    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


def ollama_tags_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() not in {
        "localhost", "127.0.0.1", "::1",
    }:
        raise LocalModelError("Local model discovery is restricted to Ollama on this computer.", 400)
    return urlunparse((parsed.scheme, parsed.netloc, "/api/tags", "", "", ""))


def parse_models(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise LocalModelError("Ollama returned an unreadable model list.")
    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in payload["models"]:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("model") or entry.get("name")
        if not isinstance(model_id, str) or not model_id or model_id in seen:
            continue
        seen.add(model_id)
        details = entry.get("details") or {}
        models.append({
            "id": model_id,
            "name": model_id,
            "size": entry.get("size") or 0,
            "family": details.get("family") or "",
            "parameter_size": details.get("parameter_size") or "",
            "quantization_level": details.get("quantization_level") or "",
            "modified_at": entry.get("modified_at") or "",
        })
    models.sort(key=lambda model: model["name"].lower())
    return models


def list_models(base_url: str) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        ollama_tags_url(base_url),
        headers={"Accept": "application/json", "User-Agent": "DataMind"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            models = parse_models(json.loads(response.read().decode("utf-8")))
    except urllib.error.HTTPError as exc:
        raise LocalModelError(f"Ollama returned HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LocalModelError(
            "Could not reach Ollama. Start Ollama, then refresh the local model list."
        ) from exc
    except json.JSONDecodeError as exc:
        raise LocalModelError("Ollama returned an unreadable model list.") from exc
    if not models:
        raise LocalModelError("Ollama is running, but no local models are installed.", 400)
    return models
