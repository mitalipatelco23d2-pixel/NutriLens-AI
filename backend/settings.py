from __future__ import annotations

import os
from dataclasses import dataclass


def _csv_environment(name: str, default: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in os.getenv(name, default).split(",") if value.strip())


@dataclass(frozen=True)
class Settings:
    app_environment: str = os.getenv("APP_ENVIRONMENT", "development")
    college_demo_mode: bool = os.getenv("COLLEGE_DEMO_MODE", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    cors_origins: tuple[str, ...] = _csv_environment("CORS_ORIGINS", "http://localhost:3000")
    postgres_url: str = os.getenv(
        "POSTGRES_URL", "postgresql://nutrilens:nutrilens_dev_only@localhost:5432/nutrilens"
    )
    persistence_backend: str = os.getenv("PERSISTENCE_BACKEND", "memory")
    auto_migrate: bool = os.getenv("AUTO_MIGRATE", "false").lower() in {"1", "true", "yes"}
    mongodb_url: str = os.getenv(
        "MONGODB_URL", "mongodb://nutrilens:nutrilens_dev_only@localhost:27017/admin"
    )
    neo4j_url: str = os.getenv("NEO4J_URL", "bolt://localhost:7687")
    neo4j_user: str = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password: str = os.getenv("NEO4J_PASSWORD", "nutrilens_dev_only")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    rate_limit_backend: str = os.getenv("RATE_LIMIT_BACKEND", "memory")
    jwt_secret: str = os.getenv("JWT_SECRET", "replace_before_non_local_use_at_least_32_bytes")
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    jwt_access_token_minutes: int = int(os.getenv("JWT_ACCESS_TOKEN_MINUTES", "30"))
    # Canonical Web OAuth Client ID used as ID-token audience
    google_server_client_id: str = os.getenv(
        "GOOGLE_SERVER_CLIENT_ID", os.getenv("GOOGLE_CLIENT_ID", "")
    )
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", os.getenv("GOOGLE_SERVER_CLIENT_ID", ""))

    def __post_init__(self) -> None:
        if not self.google_server_client_id and self.google_client_id:
            object.__setattr__(self, "google_server_client_id", self.google_client_id)
        elif not self.google_client_id and self.google_server_client_id:
            object.__setattr__(self, "google_client_id", self.google_server_client_id)

    public_web_url: str = os.getenv("PUBLIC_WEB_URL", "http://localhost:3000")
    email_auth_enabled: bool = os.getenv("EMAIL_AUTH_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    email_provider: str = os.getenv(
        "EMAIL_PROVIDER", "resend" if os.getenv("RESEND_API_KEY") else "none"
    )
    email_from: str = os.getenv("EMAIL_FROM", os.getenv("RESEND_FROM_EMAIL", ""))
    resend_api_key: str = os.getenv("RESEND_API_KEY", "")
    email_verification_minutes: int = int(os.getenv("EMAIL_VERIFICATION_MINUTES", "30"))
    password_reset_minutes: int = int(os.getenv("PASSWORD_RESET_MINUTES", "20"))
    auth_max_password_attempts: int = int(os.getenv("AUTH_MAX_PASSWORD_ATTEMPTS", "5"))
    auth_lock_minutes: int = int(os.getenv("AUTH_LOCK_MINUTES", "15"))
    phone_auth_enabled: bool = os.getenv("PHONE_AUTH_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    phone_otp_provider: str = os.getenv("PHONE_OTP_PROVIDER", "none")
    firebase_project_id: str = os.getenv("FIREBASE_PROJECT_ID", "")
    swiggy_mcp_url: str = os.getenv("SWIGGY_MCP_URL", "https://mcp.swiggy.com/im")
    swiggy_client_id: str = os.getenv("SWIGGY_CLIENT_ID", "")
    swiggy_client_secret: str = os.getenv("SWIGGY_CLIENT_SECRET", "")
    llm_provider: str = os.getenv("LLM_PROVIDER", "none")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_model: str = os.getenv("LLM_MODEL", "")
    llm_service_token: str = os.getenv("LLM_SERVICE_TOKEN", "")
    llm_timeout_seconds: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))
    semantic_rag_enabled: bool = os.getenv("SEMANTIC_RAG_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    semantic_rag_model_id: str = os.getenv(
        "SEMANTIC_RAG_MODEL_ID", "sentence-transformers/all-MiniLM-L6-v2"
    )
    semantic_rag_model_path: str = os.getenv(
        "SEMANTIC_RAG_MODEL_PATH", ".model-cache/rag/all-MiniLM-L6-v2"
    )
    semantic_rag_index_dir: str = os.getenv("SEMANTIC_RAG_INDEX_DIR", "databases/faiss/knowledge")
    semantic_rag_min_score: float = float(os.getenv("SEMANTIC_RAG_MIN_SCORE", "0.35"))
    ai_worker_provider: str = os.getenv("AI_WORKER_PROVIDER", "none").strip().lower()
    ai_worker_url: str = os.getenv("AI_WORKER_URL", "")
    ai_worker_token: str = os.getenv("AI_WORKER_TOKEN", "")
    ai_runtime_public_validated: bool = os.getenv(
        "AI_RUNTIME_PUBLIC_VALIDATED", "false"
    ).lower() in {"1", "true", "yes"}
    android_client_inference_mode: str = (
        os.getenv("ANDROID_CLIENT_INFERENCE_MODE", "shadow").strip().lower()
    )
    android_client_preferred_user_ids: tuple[str, ...] = tuple(
        item.strip()
        for item in os.getenv("ANDROID_CLIENT_PREFERRED_USER_IDS", "").split(",")
        if item.strip()
    )
    android_client_min_positioned_lines: int = int(
        os.getenv("ANDROID_CLIENT_MIN_POSITIONED_LINES", "6")
    )
    android_client_min_positioned_ratio: float = float(
        os.getenv("ANDROID_CLIENT_MIN_POSITIONED_RATIO", "0.65")
    )
    android_client_min_nutrition_rows: int = int(
        os.getenv("ANDROID_CLIENT_MIN_NUTRITION_ROWS", "4")
    )
    android_client_min_major_nutrients: int = int(
        os.getenv("ANDROID_CLIENT_MIN_MAJOR_NUTRIENTS", "3")
    )
    android_client_min_nutrition_confidence: float = float(
        os.getenv("ANDROID_CLIENT_MIN_NUTRITION_CONFIDENCE", "0.58")
    )
    razorpay_mode: str = os.getenv("RAZORPAY_MODE", "test")
    razorpay_key_id: str = os.getenv("RAZORPAY_KEY_ID", "")
    razorpay_key_secret: str = os.getenv("RAZORPAY_KEY_SECRET", "")
    razorpay_webhook_secret: str = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    razorpay_webhook_max_bytes: int = int(os.getenv("RAZORPAY_WEBHOOK_MAX_BYTES", str(256 * 1024)))
    r3_max_upload_bytes: int = int(os.getenv("R3_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    r3_min_image_dimension: int = int(os.getenv("R3_MIN_IMAGE_DIMENSION", "64"))
    r3_max_image_dimension: int = int(os.getenv("R3_MAX_IMAGE_DIMENSION", "12000"))
    r3_max_image_pixels: int = int(os.getenv("R3_MAX_IMAGE_PIXELS", "20000000"))
    r3_max_product_pixels: int = int(os.getenv("R3_MAX_PRODUCT_PIXELS", "40000000"))
    r3_scan_timeout_seconds: float = float(os.getenv("R3_SCAN_TIMEOUT_SECONDS", "180"))
    ai_worker_max_concurrent_scans: int = int(os.getenv("AI_WORKER_MAX_CONCURRENT_SCANS", "1"))
    ai_worker_queue_timeout_seconds: float = float(
        os.getenv("AI_WORKER_QUEUE_TIMEOUT_SECONDS", "120")
    )
    ai_worker_capacity_retry_attempts: int = int(
        os.getenv("AI_WORKER_CAPACITY_RETRY_ATTEMPTS", "10")
    )
    ai_worker_capacity_retry_base_seconds: float = float(
        os.getenv("AI_WORKER_CAPACITY_RETRY_BASE_SECONDS", "2")
    )
    scan_job_dispatch_concurrency: int = int(os.getenv("SCAN_JOB_DISPATCH_CONCURRENCY", "5"))
    scan_job_poll_seconds: float = float(os.getenv("SCAN_JOB_POLL_SECONDS", "1"))
    scan_job_timeout_seconds: float = float(os.getenv("SCAN_JOB_TIMEOUT_SECONDS", "180"))
    scan_job_queue_ttl_seconds: int = int(os.getenv("SCAN_JOB_QUEUE_TTL_SECONDS", "300"))
    r3_device: str = os.getenv("R3_DEVICE", "auto")
    r3_allow_model_downloads: bool = os.getenv("R3_ALLOW_MODEL_DOWNLOADS", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    r3_model_cache: str = os.getenv("R3_MODEL_CACHE", ".model-cache/r3")


settings = Settings()
