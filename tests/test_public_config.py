from pathlib import Path

from scripts.validate_public_config import (
    REQUIRED_KEYS,
    validate_public_configuration,
    validate_template,
)


def _valid_environment() -> dict[str, str]:
    result = {key: "configured" for key in REQUIRED_KEYS}
    result.update(
        {
            "PUBLIC_WEBSITE_URL": "https://nutrilens.tech",
            "PUBLIC_API_URL": "https://api.nutrilens.tech",
            "ANDROID_APP_LINK": "https://nutrilens.tech/downloads/android",
            "BACKEND_INTERNAL_URL": "https://api.nutrilens.tech",
            "NEXT_PUBLIC_API_URL": "https://api.nutrilens.tech",
            "NEXT_PUBLIC_GOOGLE_CLIENT_ID": "123.apps.googleusercontent.com",
            "GOOGLE_CLIENT_ID": "123.apps.googleusercontent.com",
            "NEXT_PUBLIC_SUPPORT_EMAIL": "support@nutrilens.tech",
            "LEGAL_POLICIES_APPROVED": "true",
            "APP_ENVIRONMENT": "production",
            "CORS_ORIGINS": "https://nutrilens.tech",
            "POSTGRES_URL": "postgresql://user:secret@db.invalid/app?sslmode=require",
            "PERSISTENCE_BACKEND": "postgres",
            "AUTO_MIGRATE": "true",
            "RATE_LIMIT_BACKEND": "redis",
            "REDIS_URL": "rediss://user:secret@cache.invalid:6380/0",
            "JWT_SECRET": "a-random-test-secret-with-at-least-32-bytes",
            "JWT_ALGORITHM": "HS256",
            "RAZORPAY_MODE": "test",
            "RAZORPAY_KEY_ID": "rzp_test_nonsecretfixture",
            "RAZORPAY_KEY_SECRET": "test-key-secret-value",
            "RAZORPAY_WEBHOOK_SECRET": "test-webhook-secret-value",
        }
    )
    plan_keys = (key for key in REQUIRED_KEYS if key.startswith("RAZORPAY_PLAN_"))
    for index, key in enumerate(plan_keys):
        result[key] = f"plan_test_{index}"
    return result


def test_public_configuration_accepts_complete_safe_topology() -> None:
    assert validate_public_configuration(_valid_environment()) == []


def test_public_configuration_reports_fields_without_secret_values() -> None:
    environment = _valid_environment()
    environment["JWT_SECRET"] = "sensitive-short-value"
    environment["PUBLIC_API_URL"] = "http://localhost:8000"
    errors = validate_public_configuration(environment)
    assert any(error.startswith("JWT_SECRET:") for error in errors)
    assert any(error.startswith("PUBLIC_API_URL:") for error in errors)
    assert all("sensitive-short-value" not in error for error in errors)


def test_example_template_declares_every_public_configuration_key() -> None:
    assert validate_template(Path(".env.example")) == []


def test_render_blueprint_declares_every_razorpay_plan_mapping() -> None:
    blueprint = Path("render.yaml").read_text(encoding="utf-8")
    plan_keys = (key for key in REQUIRED_KEYS if key.startswith("RAZORPAY_PLAN_"))
    assert all(f"- key: {key}" in blueprint for key in plan_keys)
