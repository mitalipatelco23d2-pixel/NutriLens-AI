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
