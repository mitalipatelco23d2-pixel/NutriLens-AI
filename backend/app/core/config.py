from __future__ import annotations

from dotenv import load_dotenv
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
RISK_MODEL_SHA256 = "55397e61da7b9e6b22c88d2757c75dcd8b1b8b894f93a63ca59752bb159f50e8"
RISK_VECTORIZER_SHA256 = (
    "ca053bfc80dca02de68e21294f675a2416aa62be3377f6c0ffb8eef9affda677"
)
load_dotenv(REPOSITORY_ROOT / ".env")


def _path_from_env(name: str, default: Path) -> Path:
    value = os.getenv(name)
    if not value:
        return default.resolve()
    path = Path(value).expanduser()
    return (path if path.is_absolute() else REPOSITORY_ROOT / path).resolve()


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _choice(name: str, default: str, supported: set[str]) -> str:
    value = os.getenv(name, default).strip().casefold()
    if value not in supported:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(supported))}")
    return value


def _optional_sha256(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if not value or not value.strip():
        return None
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{name} must be a 64-character hexadecimal SHA-256 digest")
    return normalized


@dataclass(frozen=True)
class Settings:
    repository_root: Path
    backend_root: Path
    frontend_dir: Path
    data_dir: Path
    processed_data_dir: Path
    model_path: Path
    risk_model_path: Path
    risk_vectorizer_path: Path
    risk_model_sha256: str | None
    risk_vectorizer_sha256: str | None
    risk_sklearn_version: str
    database_url: str
    jwt_secret_key: str
    jwt_algorithm: str
    jwt_expire_minutes: int
    max_upload_bytes: int
    max_image_pixels: int
    ocr_language: str
    ocr_engine: str
    tesseract_cmd: str | None
    cors_origins: tuple[str, ...]
    log_level: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    data_dir = _path_from_env("NUTRILENS_DATA_DIR", REPOSITORY_ROOT / "data")
    processed_dir = _path_from_env(
        "NUTRILENS_PROCESSED_DATA_DIR", data_dir / "processed"
    )

    database_url = os.getenv("NUTRILENS_DATABASE_URL")
    if not database_url:
        database_path = data_dir / "nutrilens.db"
        database_url = f"sqlite:///{database_path.as_posix()}"

    origins = tuple(
        origin.strip()
        for origin in os.getenv(
            "NUTRILENS_CORS_ORIGINS",
            "http://localhost:3000,http://localhost:5173",
        ).split(",")
        if origin.strip()
    )
    return Settings(
        repository_root=REPOSITORY_ROOT,
        backend_root=BACKEND_ROOT,
        frontend_dir=_path_from_env(
            "NUTRILENS_FRONTEND_DIR", REPOSITORY_ROOT / "frontend"
        ),
        data_dir=data_dir,
        processed_data_dir=processed_dir,
        model_path=_path_from_env(
            "NUTRILENS_MODEL_PATH",
            processed_dir / "health_score_model.joblib",
        ),
        risk_model_path=_path_from_env(
            "NUTRILENS_RISK_MODEL_PATH",
            processed_dir / "m2" / "health_risk_model.pkl",
        ),
        risk_vectorizer_path=_path_from_env(
            "NUTRILENS_RISK_VECTORIZER_PATH",
            processed_dir / "m2" / "tfidf_vectorizer.pkl",
        ),
        risk_model_sha256=_optional_sha256(
            "NUTRILENS_RISK_MODEL_SHA256", RISK_MODEL_SHA256
        ),
        risk_vectorizer_sha256=_optional_sha256(
            "NUTRILENS_RISK_VECTORIZER_SHA256", RISK_VECTORIZER_SHA256
        ),
        risk_sklearn_version=(
            os.getenv("NUTRILENS_RISK_SKLEARN_VERSION", "1.9.1").strip()
            or "1.9.1"
        ),
        database_url=database_url,
        jwt_secret_key=os.getenv(
            "NUTRILENS_JWT_SECRET_KEY",
            "nutrilens-dev-secret-change-before-deployment",
        ),
        jwt_algorithm="HS256",
        jwt_expire_minutes=_positive_int(
            "NUTRILENS_JWT_EXPIRE_MINUTES",
            60,
        ),
        max_upload_bytes=_positive_int("NUTRILENS_MAX_UPLOAD_BYTES", 8 * 1024 * 1024),
        max_image_pixels=_positive_int("NUTRILENS_MAX_IMAGE_PIXELS", 25_000_000),
        ocr_language=os.getenv("NUTRILENS_OCR_LANGUAGE", "eng").strip() or "eng",
        ocr_engine=_choice("NUTRILENS_OCR_ENGINE", "tesseract", {"tesseract"}),
        tesseract_cmd=os.getenv("NUTRILENS_TESSERACT_CMD") or None,
        cors_origins=origins,
        log_level=os.getenv("NUTRILENS_LOG_LEVEL", "INFO").upper(),
    )
