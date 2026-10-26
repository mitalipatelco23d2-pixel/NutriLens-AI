"""Fail-closed validation for owner-supplied R20 public deployment configuration."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import urlparse

REQUIRED_KEYS = (
    "PUBLIC_WEBSITE_URL",
    "PUBLIC_API_URL",
    "ANDROID_APP_LINK",
    "BACKEND_INTERNAL_URL",
    "NEXT_PUBLIC_API_URL",
    "NEXT_PUBLIC_GOOGLE_CLIENT_ID",
    "NEXT_PUBLIC_SUPPORT_EMAIL",
    "LEGAL_POLICIES_APPROVED",
    "APP_ENVIRONMENT",
    "CORS_ORIGINS",
    "POSTGRES_URL",
    "PERSISTENCE_BACKEND",
    "AUTO_MIGRATE",
    "RATE_LIMIT_BACKEND",
    "REDIS_URL",
    "JWT_SECRET",
    "JWT_ALGORITHM",
    "GOOGLE_CLIENT_ID",
    "RAZORPAY_MODE",
    "RAZORPAY_KEY_ID",
    "RAZORPAY_KEY_SECRET",
    "RAZORPAY_WEBHOOK_SECRET",
    "RAZORPAY_PLAN_PLUS_MONTHLY",
    "RAZORPAY_PLAN_PLUS_ANNUAL",
    "RAZORPAY_PLAN_PRO_MONTHLY",
    "RAZORPAY_PLAN_PRO_ANNUAL",
    "RAZORPAY_PLAN_MAX_MONTHLY",
    "RAZORPAY_PLAN_MAX_ANNUAL",
)
_PLAN_KEYS = tuple(key for key in REQUIRED_KEYS if key.startswith("RAZORPAY_PLAN_"))
_PLACEHOLDER_MARKERS = ("replace", "example", "<", ">", "${")


def _https_host(value: str) -> str | None:
    parsed = urlparse(value)
    return parsed.hostname if parsed.scheme == "https" and parsed.hostname else None


def validate_public_configuration(environment: Mapping[str, str]) -> list[str]:
    """Return field-scoped errors without ever returning configuration values."""
    errors: list[str] = []
    missing = [key for key in REQUIRED_KEYS if not environment.get(key, "").strip()]
    errors.extend(f"{key}: required" for key in missing)
    if missing:
        return errors

    website = environment["PUBLIC_WEBSITE_URL"].strip().rstrip("/")
    api = environment["PUBLIC_API_URL"].strip().rstrip("/")
    android = environment["ANDROID_APP_LINK"].strip()
    website_host = _https_host(website)
    api_host = _https_host(api)
    if website_host is None or not website_host.endswith(".tech"):
        errors.append("PUBLIC_WEBSITE_URL: must be an HTTPS .tech origin")
    if api_host is None or not api_host.startswith("api.") or not api_host.endswith(".tech"):
        errors.append("PUBLIC_API_URL: must be an HTTPS api.*.tech origin")
    if website_host and api_host and api_host != f"api.{website_host}":
        errors.append("PUBLIC_API_URL: host must be api.<PUBLIC_WEBSITE_URL host>")
    if _https_host(android) is None:
        errors.append("ANDROID_APP_LINK: must be an HTTPS public distribution URL")
    for key in ("BACKEND_INTERNAL_URL", "NEXT_PUBLIC_API_URL"):
        if environment[key].strip().rstrip("/") != api:
            errors.append(f"{key}: must equal PUBLIC_API_URL")

    cors_origins = {
        item.strip().rstrip("/") for item in environment["CORS_ORIGINS"].split(",") if item.strip()
    }
    if website not in cors_origins or "*" in cors_origins:
        errors.append("CORS_ORIGINS: must include only explicit origins including the website")
    if any(_https_host(origin) is None for origin in cors_origins):
        errors.append("CORS_ORIGINS: every public origin must use HTTPS")

    expected = {
        "APP_ENVIRONMENT": "production",
        "PERSISTENCE_BACKEND": "postgres",
        "AUTO_MIGRATE": "true",
        "RATE_LIMIT_BACKEND": "redis",
        "JWT_ALGORITHM": "HS256",
        "RAZORPAY_MODE": "test",
        "LEGAL_POLICIES_APPROVED": "true",
    }
    for key, value in expected.items():
        if environment[key].strip().casefold() != value.casefold():
            errors.append(f"{key}: must be {value}")
    if not environment["POSTGRES_URL"].startswith(("postgresql://", "postgres://")):
        errors.append("POSTGRES_URL: must be a PostgreSQL URL")
    if "sslmode=require" not in environment["POSTGRES_URL"].casefold():
        errors.append("POSTGRES_URL: must require TLS with sslmode=require")
    if not environment["REDIS_URL"].startswith("rediss://"):
        errors.append("REDIS_URL: must use TLS (rediss://)")
    if len(environment["JWT_SECRET"].encode("utf-8")) < 32:
        errors.append("JWT_SECRET: must contain at least 32 bytes")

    web_client = environment["NEXT_PUBLIC_GOOGLE_CLIENT_ID"].strip()
    api_client = environment["GOOGLE_CLIENT_ID"].strip()
    if web_client != api_client or not web_client.endswith(".apps.googleusercontent.com"):
        errors.append("GOOGLE_CLIENT_ID: web and API audience IDs must match a Google client ID")
    support_email = environment["NEXT_PUBLIC_SUPPORT_EMAIL"].strip()
    if support_email.count("@") != 1 or "." not in support_email.rsplit("@", 1)[1]:
        errors.append("NEXT_PUBLIC_SUPPORT_EMAIL: must be a public organization-owned email")
    if not environment["RAZORPAY_KEY_ID"].startswith("rzp_test_"):
        errors.append("RAZORPAY_KEY_ID: must be a Razorpay Test Mode key ID")
    for key in ("RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"):
        if len(environment[key]) < 16:
            errors.append(f"{key}: must contain at least 16 characters")
    plan_ids = [environment[key].strip() for key in _PLAN_KEYS]
    if any(not plan_id.startswith("plan_") for plan_id in plan_ids):
        errors.append("RAZORPAY_PLAN_*: every paid interval must map to a provider plan ID")
    if len(set(plan_ids)) != len(plan_ids):
        errors.append("RAZORPAY_PLAN_*: the six provider plan IDs must be distinct")

    for key in REQUIRED_KEYS:
        if any(marker in environment[key].casefold() for marker in _PLACEHOLDER_MARKERS):
            errors.append(f"{key}: placeholder values are not allowed")
    return list(dict.fromkeys(errors))


def validate_template(path: Path) -> list[str]:
    declared = {
        line.split("=", 1)[0].strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }
    return [
        f"{key}: missing from configuration template"
        for key in REQUIRED_KEYS
        if key not in declared
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    errors = (
        validate_template(args.template)
        if args.template
        else validate_public_configuration(os.environ)
    )
    payload = {"status": "ready" if not errors else "not_ready", "errors": errors}
    print(
        json.dumps(payload, indent=2)
        if args.json
        else "\n".join(errors or ["Public configuration is ready."])
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
