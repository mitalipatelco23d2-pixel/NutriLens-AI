from pathlib import Path

import pytest

from backend.app.core import config as config_module
from backend.app.core.config import BACKEND_ROOT, REPOSITORY_ROOT, get_settings


def test_repository_paths_are_deterministic(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    settings = get_settings()
    assert REPOSITORY_ROOT == Path(config_module.__file__).resolve().parents[3]
    assert BACKEND_ROOT == REPOSITORY_ROOT / "backend"
    assert settings.frontend_dir == REPOSITORY_ROOT / "frontend"
    assert settings.data_dir == REPOSITORY_ROOT / "data"
    assert settings.processed_data_dir == REPOSITORY_ROOT / "data" / "processed"
    assert settings.model_path == REPOSITORY_ROOT / "data" / "processed" / "health_score_model.joblib"
    assert settings.m5_shap_enabled is False
    assert settings.m5_shap_top_features == 8
    assert settings.m5_shap_max_features == 3_000
    assert settings.m5_shap_max_nonzero_features == 512
    assert settings.m5_shap_max_trees == 250
    assert settings.m5_shap_max_runtime_ms == 2_000
    assert settings.m5_shap_additivity_tolerance == 1e-6
    assert settings.m5_rag_enabled is False
    assert settings.m5_rag_corpus_dir == REPOSITORY_ROOT / "data" / "processed" / "rag"
    assert settings.m5_rag_jurisdiction == "IN"
    assert settings.m5_rag_top_k == 6
    assert settings.m5_rag_min_score == 1.0
    assert settings.m5_rag_max_per_source == 2
    assert settings.m5_rag_timeout_seconds == 12.0
    assert settings.m5_rag_retries == 1
    assert settings.m5_rag_max_tokens == 500
    assert settings.m5_rag_max_input_chars == 18_000
    assert settings.m5_rag_concurrency == 1
    assert settings.m5_rag_max_daily_requests == 20
    assert (
        settings.cloudflare_model_id
        == "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    )


def test_relative_environment_paths_are_repository_relative(monkeypatch):
    monkeypatch.setenv("NUTRILENS_MODEL_PATH", "artifacts/model.joblib")
    monkeypatch.setenv("NUTRILENS_FRONTEND_DIR", "demo")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.model_path == (REPOSITORY_ROOT / "artifacts/model.joblib").resolve()
    assert settings.frontend_dir == (REPOSITORY_ROOT / "demo").resolve()
    get_settings.cache_clear()


def test_absolute_environment_path_is_preserved(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("NUTRILENS_MODEL_PATH", str(tmp_path / "model.joblib"))
    get_settings.cache_clear()
    assert get_settings().model_path == (tmp_path / "model.joblib").resolve()
    get_settings.cache_clear()


def test_invalid_configured_ocr_engine_is_rejected(monkeypatch):
    monkeypatch.setenv("NUTRILENS_OCR_ENGINE", "easyocr")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="NUTRILENS_OCR_ENGINE"):
        get_settings()
    get_settings.cache_clear()


def test_shap_must_be_explicitly_enabled_with_valid_limits(monkeypatch):
    monkeypatch.setenv("NUTRILENS_M5_SHAP_ENABLED", "true")
    monkeypatch.setenv("NUTRILENS_M5_SHAP_TOP_FEATURES", "5")
    monkeypatch.setenv("NUTRILENS_M5_SHAP_ADDITIVITY_TOLERANCE", "0.00001")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.m5_shap_enabled is True
    assert settings.m5_shap_top_features == 5
    assert settings.m5_shap_additivity_tolerance == 1e-5
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("NUTRILENS_M5_SHAP_ENABLED", "sometimes"),
        ("NUTRILENS_M5_SHAP_MAX_RUNTIME_MS", "0"),
        ("NUTRILENS_M5_SHAP_ADDITIVITY_TOLERANCE", "nan"),
    ],
)
def test_invalid_shap_configuration_is_rejected(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    with pytest.raises(ValueError, match=name):
        get_settings()
    get_settings.cache_clear()


def test_rag_must_be_explicitly_enabled_with_bounded_limits(monkeypatch):
    monkeypatch.setenv("NUTRILENS_M5_RAG_ENABLED", "true")
    monkeypatch.setenv("NUTRILENS_M5_RAG_TOP_K", "4")
    monkeypatch.setenv("NUTRILENS_M5_RAG_RETRIES", "0")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.m5_rag_enabled is True
    assert settings.m5_rag_top_k == 4
    assert settings.m5_rag_retries == 0
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("NUTRILENS_M5_RAG_ENABLED", "sometimes"),
        ("NUTRILENS_M5_RAG_RETRIES", "2"),
        ("NUTRILENS_M5_RAG_MIN_SCORE", "0"),
        ("NUTRILENS_CLOUDFLARE_MODEL_ID", "@cf/paid/other-model"),
    ],
)
def test_invalid_rag_configuration_is_rejected(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    with pytest.raises(ValueError, match=name):
        get_settings()
    get_settings.cache_clear()
