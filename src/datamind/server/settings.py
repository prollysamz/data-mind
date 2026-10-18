"""Persistent UI settings for the selected model provider.

Secrets stay in a local, gitignored JSON file. Public API responses expose only
whether a key exists, where it came from, and a short suffix for identification.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

DEFAULT_PATH = ".datamind/settings.json"
PROVIDERS = ("local", "openrouter", "google")


class SettingsStore:
    def __init__(self, path: str | Path | None = None, *, default_local_model: str = "") -> None:
        self.path = Path(path or os.environ.get("DATAMIND_SETTINGS_PATH") or DEFAULT_PATH)
        self.default_local_model = default_local_model
        self._lock = threading.Lock()
        self._data: dict[str, Any] = self._read()

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix="settings-",
            suffix=".tmp",
            delete=False,
        ) as file:
            tmp = Path(file.name)
            try:
                tmp.chmod(0o600)
                json.dump(data, file, indent=2)
                file.flush()
                os.fsync(file.fileno())
            except Exception:
                file.close()
                tmp.unlink(missing_ok=True)
                raise
        try:
            tmp.replace(self.path)
        finally:
            tmp.unlink(missing_ok=True)

    @property
    def provider(self) -> str:
        value = self._data.get("provider", "local")
        return value if value in PROVIDERS else "local"

    @property
    def local_model(self) -> str:
        return str(self._data.get("local_model") or self.default_local_model)

    @property
    def openrouter_model(self) -> str:
        return str(self._data.get("openrouter_model") or "")

    @property
    def openrouter_api_key(self) -> str:
        return str(self._data.get("openrouter_api_key") or os.environ.get("OPENROUTER_API_KEY", ""))

    @property
    def google_model(self) -> str:
        return str(self._data.get("google_model") or "")

    @property
    def google_api_key(self) -> str:
        # Google documents GOOGLE_API_KEY as taking precedence when both are set.
        return str(
            self._data.get("google_api_key")
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("GEMINI_API_KEY", "")
        )

    # Backward-compatible aliases for the first settings implementation.
    @property
    def model(self) -> str:
        return self.openrouter_model

    @property
    def api_key(self) -> str:
        return self.openrouter_api_key

    def _key_source(self, saved_field: str, environment_names: tuple[str, ...]) -> str | None:
        if self._data.get(saved_field):
            return "saved"
        if any(os.environ.get(name) for name in environment_names):
            return "environment"
        return None

    @staticmethod
    def _key_public(key: str, source: str | None) -> dict[str, Any]:
        return {
            "configured": bool(key),
            "key_source": source,
            "key_hint": f"…{key[-4:]}" if len(key) >= 8 else ("set" if key else ""),
        }

    def openrouter_active(self) -> bool:
        return self.provider == "openrouter" and bool(self.openrouter_api_key) and bool(self.openrouter_model)

    def google_active(self) -> bool:
        return self.provider == "google" and bool(self.google_api_key) and bool(self.google_model)

    def update(
        self,
        *,
        provider: str | None = None,
        local_model: str | None = None,
        openrouter_model: str | None = None,
        openrouter_api_key: str | None = None,
        google_model: str | None = None,
        google_api_key: str | None = None,
        # Legacy keyword names remain supported for callers and older tests.
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        if openrouter_model is None:
            openrouter_model = model
        if openrouter_api_key is None:
            openrouter_api_key = api_key
        with self._lock:
            updated = dict(self._data)
            values = {
                "provider": provider,
                "local_model": local_model,
                "openrouter_model": openrouter_model,
                "google_model": google_model,
            }
            for field, value in values.items():
                if value is not None:
                    updated[field] = value
            for field, value in (
                ("openrouter_api_key", openrouter_api_key),
                ("google_api_key", google_api_key),
            ):
                if value is not None:
                    if value:
                        updated[field] = value
                    else:
                        updated.pop(field, None)
            self._write(updated)
            self._data = updated

    def openrouter_credentials(self) -> tuple[str, str]:
        with self._lock:
            return self.openrouter_api_key, self.openrouter_model

    def google_credentials(self) -> tuple[str, str]:
        with self._lock:
            return self.google_api_key, self.google_model

    def credentials(self) -> tuple[str, str, str]:
        """Backward-compatible OpenRouter credential snapshot."""
        with self._lock:
            return self.provider, self.openrouter_api_key, self.openrouter_model

    def public(self) -> dict[str, Any]:
        openrouter_key = self.openrouter_api_key
        google_key = self.google_api_key
        return {
            "provider": self.provider,
            "local": {
                "model": self.local_model,
                "active": self.provider == "local" and bool(self.local_model),
            },
            "openrouter": {
                **self._key_public(
                    openrouter_key,
                    self._key_source("openrouter_api_key", ("OPENROUTER_API_KEY",)),
                ),
                "model": self.openrouter_model,
                "active": self.openrouter_active(),
            },
            "google": {
                **self._key_public(
                    google_key,
                    self._key_source("google_api_key", ("GOOGLE_API_KEY", "GEMINI_API_KEY")),
                ),
                "model": self.google_model,
                "active": self.google_active(),
            },
        }
