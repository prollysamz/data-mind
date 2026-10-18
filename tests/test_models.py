"""Unit tests for ModelRegistry, preset configuration, and privacy classifications."""

from datamind.llm.models import KNOWN_MODELS, PRESETS, ModelRegistry


def test_registry_lists_models():
    reg = ModelRegistry()
    models = reg.list_models()
    assert len(models) == len(KNOWN_MODELS)
    ids = {m.id for m in models}
    assert "gemma4:e2b" in ids
    assert "google.gemma-4-26b-a4b" in ids


def test_cloud_model_disabled_without_env(monkeypatch):
    monkeypatch.delenv("DATAMIND_ALLOW_CLOUD", raising=False)
    reg = ModelRegistry()
    valid, msg, _model_info = reg.validate_model_selection("google.gemma-4-26b-a4b")
    assert valid is False
    assert "DATAMIND_ALLOW_CLOUD=1 is not set" in msg


def test_local_model_always_allowed(monkeypatch):
    monkeypatch.delenv("DATAMIND_ALLOW_CLOUD", raising=False)
    reg = ModelRegistry()
    valid, _msg, model_info = reg.validate_model_selection("gemma4:e2b")
    assert valid is True
    assert model_info.privacy_class == "LOCAL_PRIVATE"


def test_presets_structure():
    assert "local" in PRESETS
    assert "hybrid_privacy" in PRESETS
    assert "cloud_accuracy" in PRESETS
    assert "second_opinion" in PRESETS
    assert PRESETS["local"]["requires_cloud"] is False
    assert PRESETS["hybrid_privacy"]["requires_cloud"] is True


def test_unknown_model_rejected():
    reg = ModelRegistry()
    valid, msg, _ = reg.validate_model_selection("unknown-model-xyz")
    assert valid is False
    assert "Unknown model ID" in msg
