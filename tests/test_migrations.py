from pathlib import Path


def test_v1_postgres_migration_covers_transactional_domains() -> None:
    sql = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(Path("backend/migrations").glob("*.sql"))
    )
    required_tables = {
        "users",
        "health_profiles",
        "account_profiles",
        "household_profiles",
        "scans",
        "diary_entries",
        "pantry_items",
        "assistant_usage",
        "scan_usage",
        "subscriptions",
        "payments",
        "payment_events",
        "notifications",
        "favorites",
        "shopping_list_items",
        "auth_identities",
        "password_credentials",
        "auth_action_tokens",
        "auth_sessions",
        "auth_security_events",
        "phone_otp_challenges",
        "email_otp_challenges",
    }
    for table in required_tables:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    assert "ON DELETE CASCADE" in sql
    assert "payload JSONB NOT NULL" in sql
    assert "terms_accepted_at TIMESTAMPTZ" in sql
    assert "privacy_accepted_at TIMESTAMPTZ" in sql


def test_mutable_diary_and_pantry_rows_have_update_timestamps() -> None:
    sql = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(Path("backend/migrations").glob("*.sql"))
    )

    for table in ("diary_entries", "pantry_items"):
        assert (
            f"ALTER TABLE {table}\n"
            "    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();"
        ) in sql
