import hashlib
import hmac
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from backend.auth import create_session_token, user_store
from backend.entitlements import BillingInterval, PlanCode, SpecialRole, SubscriptionStatus
from backend.main import app
from backend.payments import (
    SubscriptionRecord,
    SubscriptionStateStore,
    _require_private_test_operator,
    verify_checkout_signature,
    verify_webhook_signature,
)


def test_checkout_signature_verification_rejects_tampering() -> None:
    secret = "test-secret"
    expected = hmac.new(secret.encode(), b"pay_123|sub_123", hashlib.sha256).hexdigest()

    assert verify_checkout_signature(
        payment_id="pay_123", subscription_id="sub_123", signature=expected, secret=secret
    )
    assert not verify_checkout_signature(
        payment_id="pay_tampered",
        subscription_id="sub_123",
        signature=expected,
        secret=secret,
    )


def test_webhook_signature_verification_uses_raw_body() -> None:
    body = b'{"event":"subscription.activated"}'
    secret = "webhook-secret"
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    assert verify_webhook_signature(body=body, signature=signature, secret=secret)
    assert not verify_webhook_signature(body=body + b" ", signature=signature, secret=secret)


def test_webhook_rejects_oversized_body_before_signature_check(monkeypatch) -> None:
    import backend.payments as payments

    monkeypatch.setattr(
        payments, "settings", replace(payments.settings, razorpay_webhook_max_bytes=4)
    )
    response = TestClient(app).post(
        "/api/v1/payments/webhooks/razorpay",
        content=b"12345",
        headers={"X-Razorpay-Signature": "ignored"},
    )
    assert response.status_code == 413


def test_webhook_event_store_is_idempotent() -> None:
    store = SubscriptionStateStore()
    store.add(
        SubscriptionRecord(
            user_id="user-1",
            plan=PlanCode.PRO,
            interval=BillingInterval.MONTHLY,
            provider_subscription_id="sub_1",
            status=SubscriptionStatus.CREATED,
        )
    )

    assert store.apply_event("event-1", "sub_1", SubscriptionStatus.ACTIVE) is True
    assert store.apply_event("event-1", "sub_1", SubscriptionStatus.CANCELLED) is False
    assert store.get("sub_1").status is SubscriptionStatus.ACTIVE  # type: ignore[union-attr]
    assert store.apply_event("event-2", "sub_1", SubscriptionStatus.CREATED) is False
    assert store.get("sub_1").status is SubscriptionStatus.ACTIVE  # type: ignore[union-attr]
    newer = datetime.now(UTC)
    older = newer - timedelta(minutes=1)
    assert (
        store.apply_event(
            "event-3",
            "sub_1",
            SubscriptionStatus.PAUSED,
            provider_created_at=newer,
        )
        is True
    )
    assert (
        store.apply_event(
            "event-4",
            "sub_1",
            SubscriptionStatus.ACTIVE,
            provider_created_at=older,
        )
        is False
    )
    assert store.get("sub_1").status is SubscriptionStatus.PAUSED  # type: ignore[union-attr]
    assert (
        store.apply_event(
            "event-5",
            "sub_1",
            SubscriptionStatus.ACTIVE,
            provider_created_at=newer + timedelta(minutes=1),
        )
        is True
    )


def test_billing_account_is_private_and_reports_free_state() -> None:
    client = TestClient(app)
    assert client.get("/api/v1/payments/account").status_code == 401
    user = user_store.upsert_google_user(
        {
            "sub": "billing-account-user",
            "email": "billing@example.com",
            "email_verified": True,
            "name": "Billing User",
        }
    )
    token, _ = create_session_token(user)
    response = client.get("/api/v1/payments/account", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["plan"] == "FREE"
    assert response.json()["payments"] == []


def test_public_account_cannot_start_razorpay_test_checkout() -> None:
    client = TestClient(app)
    user = user_store.upsert_google_user(
        {
            "sub": "public-checkout-user",
            "email": "public-checkout@example.com",
            "email_verified": True,
            "name": "Public Checkout User",
        }
    )
    token, _ = create_session_token(user)

    response = client.post(
        "/api/v1/payments/subscriptions",
        headers={"Authorization": f"Bearer {token}"},
        json={"plan": "PLUS", "interval": "MONTHLY"},
    )

    assert response.status_code == 403
    assert "coming soon" in response.json()["detail"]


def test_admin_role_reaches_private_test_configuration_gate(monkeypatch) -> None:
    import backend.payments as payments

    monkeypatch.setattr(
        payments,
        "settings",
        replace(
            payments.settings,
            razorpay_mode="test",
            razorpay_key_id="rzp_test_private",
            razorpay_key_secret="private-test-secret",
        ),
    )
    user = user_store.upsert_google_user(
        {
            "sub": "private-checkout-admin",
            "email": "private-checkout-admin@example.com",
            "email_verified": True,
            "name": "Private Checkout Admin",
        }
    )
    admin = replace(user, roles=frozenset({SpecialRole.ADMIN}))

    _require_private_test_operator(admin)
