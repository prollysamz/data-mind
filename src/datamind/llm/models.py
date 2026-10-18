"""Model registry, privacy classification, capability mapping, and presets for DataMind."""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from datamind.config import AppConfig

logger = logging.getLogger(__name__)

PrivacyClass = Literal["LOCAL_PRIVATE", "CLOUD_METERED"]
ModelStatus = Literal["ready", "not_installed", "credentials_missing", "cloud_disabled"]

PRESETS: dict[str, dict[str, Any]] = {
    "local": {
        "id": "local",
        "label": "Local Only (Air-Gapped)",
        "description": "All agent stages execute 100% locally on your machine. Zero bytes leave your host.",
        "privacy_class": "LOCAL_PRIVATE",
        "default_model": "gemma4:e2b",
        "requires_cloud": False,
        "stages": {
            "planner": "gemma4:e2b",
            "sql_generator": "gemma4:e2b",
            "narrator": "gemma4:e2b",
            "classifier": "gemma4:e2b",
        },
    },
    "hybrid_privacy": {
        "id": "hybrid_privacy",
        "label": "Hybrid Privacy (Schema-Only Cloud)",
        "description": "Planner, retrieval, and narration run locally. Only SQL generation queries Bedrock with schema summary. 0 result rows or document chunks ever leave your machine.",
        "privacy_class": "CLOUD_METERED",
        "default_model": "google.gemma-4-26b-a4b",
        "requires_cloud": True,
        "stages": {
            "planner": "gemma4:e2b",
            "sql_generator": "google.gemma-4-26b-a4b",
            "narrator": "gemma4:e2b",
            "classifier": "gemma4:e2b",
        },
    },
    "cloud_accuracy": {
        "id": "cloud_accuracy",
        "label": "Cloud High Accuracy (Bedrock)",
        "description": "SQL generation and narration execute on cloud Bedrock model with verified citation checks.",
        "privacy_class": "CLOUD_METERED",
        "default_model": "google.gemma-4-26b-a4b",
        "requires_cloud": True,
        "stages": {
            "planner": "gemma4:e2b",
            "sql_generator": "google.gemma-4-26b-a4b",
            "narrator": "google.gemma-4-26b-a4b",
            "classifier": "gemma4:e2b",
        },
    },
    "second_opinion": {
        "id": "second_opinion",
        "label": "Second Opinion (Cross-Model Agreement)",
        "description": "Dual models independently generate queries; discrepancies and assumptions are highlighted.",
        "privacy_class": "LOCAL_PRIVATE",
        "default_model": "gemma4:e2b",
        "requires_cloud": False,
        "stages": {
            "primary": "gemma4:e2b",
            "secondary": "gemma4:e4b",
        },
    },
}


@dataclass
class ModelInfo:
    id: str
    label: str
    provider: str
    privacy_class: PrivacyClass
    status: ModelStatus
    status_reason: str = ""
    capabilities: dict[str, Any] = field(default_factory=dict)
    context_size: int = 8192
    price_input_m: float = 0.0
    price_output_m: float = 0.0
    pull_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


KNOWN_MODELS: list[dict[str, Any]] = [
    {
        "id": "gemma4:e2b",
        "label": "Gemma 4 E2B (Local)",
        "provider": "ollama",
        "privacy_class": "LOCAL_PRIVATE",
        "context_size": 8192,
        "capabilities": {"tools": True, "json_mode": True, "vision": False},
        "price_input_m": 0.0,
        "price_output_m": 0.0,
        "pull_hint": "ollama pull gemma4:e2b",
    },
    {
        "id": "gemma4:e4b",
        "label": "Gemma 4 E4B (Local)",
        "provider": "ollama",
        "privacy_class": "LOCAL_PRIVATE",
        "context_size": 8192,
        "capabilities": {"tools": True, "json_mode": True, "vision": False},
        "price_input_m": 0.0,
        "price_output_m": 0.0,
        "pull_hint": "ollama pull gemma4:e4b",
    },
    {
        "id": "google.gemma-4-26b-a4b",
        "label": "Gemma 4 26B A4B (AWS Bedrock)",
        "provider": "bedrock",
        "privacy_class": "CLOUD_METERED",
        "context_size": 32768,
        "capabilities": {"tools": True, "json_mode": True, "vision": False},
        "price_input_m": 0.20,
        "price_output_m": 0.60,
        "pull_hint": "Requires DATAMIND_ALLOW_CLOUD=1 and Bedrock credentials",
    },
    {
        "id": "google.gemma-4-31b",
        "label": "Gemma 4 31B (AWS Bedrock)",
        "provider": "bedrock",
        "privacy_class": "CLOUD_METERED",
        "context_size": 32768,
        "capabilities": {"tools": True, "json_mode": True, "vision": False},
        "price_input_m": 0.35,
        "price_output_m": 1.05,
        "pull_hint": "Requires DATAMIND_ALLOW_CLOUD=1 and Bedrock credentials",
    },
    {
        "id": "anthropic.claude-3-haiku",
        "label": "Claude 3 Haiku (AWS Bedrock)",
        "provider": "bedrock",
        "privacy_class": "CLOUD_METERED",
        "context_size": 32768,
        "capabilities": {"tools": True, "json_mode": True, "vision": False},
        "price_input_m": 0.25,
        "price_output_m": 1.25,
        "pull_hint": "Requires DATAMIND_ALLOW_CLOUD=1 and Bedrock credentials",
    },
]


class ModelRegistry:
    """Manages model discovery, health, capabilities, and privacy classification."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config

    def _get_installed_ollama_models(self) -> set[str]:
        """Query local Ollama instance for installed models."""
        base_url = "http://localhost:11434"
        if self.config and self.config.llm and "localhost:11434" in self.config.llm.base_url:
            base_url = self.config.llm.base_url.rstrip("/").removesuffix("/v1")
        try:
            req = urllib.request.Request(f"{base_url}/api/tags", headers={"User-Agent": "DataMind"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return {m.get("name", "") for m in data.get("models", [])}
        except Exception:
            return set()

    def list_models(self) -> list[ModelInfo]:
        """Return full list of models with current operational statuses."""
        installed_local = self._get_installed_ollama_models()
        allow_cloud = os.getenv("DATAMIND_ALLOW_CLOUD", "0") == "1"
        has_bedrock_key = bool(
            os.getenv("AWS_ACCESS_KEY_ID")
            or os.getenv("BEDROCK_API_KEY")
            or os.getenv("AWS_BEARER_TOKEN_BEDROCK")
            or os.getenv("LLM_API_KEY", "").startswith("bedrock")
            or "bedrock" in os.getenv("LLM_BASE_URL", "").lower()
        )

        results: list[ModelInfo] = []
        for item in KNOWN_MODELS:
            m_id = item["id"]
            provider = item["provider"]
            p_class = item["privacy_class"]

            if p_class == "LOCAL_PRIVATE":
                # Check if locally installed
                # If cannot connect to Ollama, assume configured default is ready for offline/mock
                if installed_local:
                    if m_id in installed_local or any(m_id in inst for inst in installed_local):
                        status: ModelStatus = "ready"
                        reason = "Installed and running locally in Ollama."
                    else:
                        status = "not_installed"
                        reason = f"Not installed in local Ollama. Run: {item['pull_hint']}"
                else:
                    # Ollama offline or mock mode
                    if m_id == "gemma4:e2b":
                        status = "ready"
                        reason = "Default local model."
                    else:
                        status = "not_installed"
                        reason = f"Ollama not running or model not pulled. Run: {item['pull_hint']}"
            else:
                # Cloud model
                if not allow_cloud:
                    status = "cloud_disabled"
                    reason = "Cloud access disabled (DATAMIND_ALLOW_CLOUD=0). Set DATAMIND_ALLOW_CLOUD=1 to enable."
                elif not has_bedrock_key:
                    status = "credentials_missing"
                    reason = "Bedrock credentials missing. Set AWS_ACCESS_KEY_ID or LLM_API_KEY."
                else:
                    status = "ready"
                    reason = "Cloud Bedrock endpoint configured and available."

            results.append(
                ModelInfo(
                    id=m_id,
                    label=item["label"],
                    provider=provider,
                    privacy_class=p_class,
                    status=status,
                    status_reason=reason,
                    capabilities=item["capabilities"],
                    context_size=item["context_size"],
                    price_input_m=item["price_input_m"],
                    price_output_m=item["price_output_m"],
                    pull_hint=item["pull_hint"],
                )
            )

        return results

    def get_model(self, model_id: str) -> ModelInfo | None:
        """Find model info by ID."""
        for m in self.list_models():
            if m.id == model_id:
                return m
        return None

    def validate_model_selection(self, model_id: str) -> tuple[bool, str, ModelInfo | None]:
        """Validate if a model can be used for execution."""
        model = self.get_model(model_id)
        if not model:
            return False, f"Unknown model ID '{model_id}'. Must be one of {[m['id'] for m in KNOWN_MODELS]}.", None

        if model.privacy_class == "CLOUD_METERED":
            if os.getenv("DATAMIND_ALLOW_CLOUD", "0") != "1":
                return False, f"Cannot use cloud model '{model_id}': DATAMIND_ALLOW_CLOUD=1 is not set.", model
            if model.status == "credentials_missing":
                return False, f"Cannot use cloud model '{model_id}': AWS / Bedrock credentials missing.", model

        return True, "Model is valid.", model

    def get_preset(self, preset_id: str) -> dict[str, Any] | None:
        """Find preset by ID."""
        return PRESETS.get(preset_id)
