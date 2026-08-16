from __future__ import annotations

from dotenv import load_dotenv
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
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


@dataclass(frozen=True)
class Settings:
    repository_root: Path
    backend_root: Path
    frontend_dir: Path
    data_dir: Path
    processed_data_dir: Path
    model_path: Path
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
