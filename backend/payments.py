"""Razorpay Test Mode integration with verified, idempotent lifecycle handling."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from threading import RLock
from typing import Annotated, Any
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from backend.auth import User, current_user
from backend.entitlements import (
    PLAN_CATALOG,
    BillingInterval,
    PlanCode,
    SpecialRole,
    SubscriptionStatus,
)
from backend.settings import settings
from backend.storage_runtime import postgres_store

router = APIRouter(prefix="/api/v1/payments", tags=["Razorpay Payments"])


async def _read_limited_body(request: Request, maximum_bytes: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_bytes = int(declared)
            if declared_bytes < 0:
                raise ValueError
            if declared_bytes > maximum_bytes:
                raise HTTPException(status_code=413, detail="Webhook body is too large.")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header.") from exc
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > maximum_bytes:
            raise HTTPException(status_code=413, detail="Webhook body is too large.")
    return bytes(body)


@dataclass(frozen=True)
class SubscriptionRecord:
    user_id: str
    plan: PlanCode
    interval: BillingInterval
    provider_subscription_id: str
    status: SubscriptionStatus


class SubscriptionStateStore:
    """Process-local adapter; production persistence can replace this boundary."""

    def __init__(self) -> None:
        self._records: dict[str, SubscriptionRecord] = {}
        self._events: set[str] = set()
        self._latest_provider_event_at: dict[str, datetime] = {}
        self._lock = RLock()

    def add(self, record: SubscriptionRecord) -> None:
        if postgres_store is not None:
            postgres_store.add_subscription(
                {
                    "user_id": record.user_id,
                    "plan": record.plan.value,
                    "interval": record.interval.value,
                    "provider_subscription_id": record.provider_subscription_id,
                    "status": record.status.value,
                }
            )
            return
        with self._lock:
            self._records[record.provider_subscription_id] = record

    def get(self, provider_subscription_id: str) -> SubscriptionRecord | None:
        if postgres_store is not None:
            row = postgres_store.get_subscription(provider_subscription_id)
            if row is None:
                return None
            return SubscriptionRecord(
                user_id=str(row["user_id"]),
                plan=PlanCode(str(row["plan_code"])),
                interval=BillingInterval(str(row["billing_interval"])),
                provider_subscription_id=str(row["provider_subscription_id"]),
                status=SubscriptionStatus(str(row["status"])),
            )
        return self._records.get(provider_subscription_id)

    def get_for_user(self, user_id: str) -> SubscriptionRecord | None:
        if postgres_store is not None:
            row = postgres_store.get_current_subscription(user_id)
            if row is None:
                return None
            return SubscriptionRecord(
                user_id=str(row["user_id"]),
                plan=PlanCode(str(row["plan_code"])),
                interval=BillingInterval(str(row["billing_interval"])),
                provider_subscription_id=str(row["provider_subscription_id"]),
                status=SubscriptionStatus(str(row["status"])),
            )
        with self._lock:
            records = [record for record in self._records.values() if record.user_id == user_id]
        return records[-1] if records else None

    def apply_event(
        self,
        event_id: str,
        provider_subscription_id: str,
        status: SubscriptionStatus,
        *,
        event_type: str = "checkout.verified",
        payload_sha256: str | None = None,
        current_period_end: datetime | None = None,
        provider_created_at: datetime | None = None,
    ) -> bool:
        """Apply an event exactly once. Returns False for a replay."""

        if postgres_store is not None:
            return postgres_store.apply_payment_event(
                event_id=event_id,
                event_type=event_type,
                provider_subscription_id=provider_subscription_id,
                status=status.value,
                payload_sha256=payload_sha256 or hashlib.sha256(event_id.encode()).hexdigest(),
                current_period_end=current_period_end,
                provider_created_at=provider_created_at,
            )
        with self._lock:
            if event_id in self._events:
                return False
            latest = self._latest_provider_event_at.get(provider_subscription_id)
            if (
                provider_created_at is not None
                and latest is not None
                and provider_created_at <= latest
            ):
                self._events.add(event_id)
                return False
            record = self._records.get(provider_subscription_id)
            if record is not None and _transition_allowed(record.status, status, event_type):
                self._records[provider_subscription_id] = replace(record, status=status)
            elif record is not None:
                self._events.add(event_id)
                return False
            self._events.add(event_id)
            if provider_created_at is not None:
                self._latest_provider_event_at[provider_subscription_id] = provider_created_at
            return True


def _transition_allowed(
    current: SubscriptionStatus, target: SubscriptionStatus, event_type: str
) -> bool:
    if event_type.startswith("owner.subscription."):
        return True
    allowed = {
        SubscriptionStatus.CREATED: {
            SubscriptionStatus.CREATED,
            SubscriptionStatus.AUTHENTICATING,
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.CANCELLED,
        },
        SubscriptionStatus.AUTHENTICATING: {
            SubscriptionStatus.AUTHENTICATING,
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.PAST_DUE,
            SubscriptionStatus.CANCELLED,
        },
        SubscriptionStatus.ACTIVE: {
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.PAST_DUE,
            SubscriptionStatus.PAUSED,
            SubscriptionStatus.CANCELLED,
        },
        SubscriptionStatus.PAST_DUE: {
            SubscriptionStatus.PAST_DUE,
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.PAUSED,
            SubscriptionStatus.CANCELLED,
        },
        SubscriptionStatus.PAUSED: {
            SubscriptionStatus.PAUSED,
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.CANCELLED,
        },
        SubscriptionStatus.CANCELLED: {SubscriptionStatus.CANCELLED},
        SubscriptionStatus.EXPIRED: {SubscriptionStatus.EXPIRED},
        SubscriptionStatus.FREE: {SubscriptionStatus.FREE},
    }
    return target in allowed.get(current, {current})


class CheckoutRequest(BaseModel):
    plan: PlanCode
    interval: BillingInterval


class CheckoutResponse(BaseModel):
    provider: str = "razorpay"
    mode: str = "test"
    key_id: str
    subscription_id: str
    plan: PlanCode
    interval: BillingInterval
    amount_paise: int
    currency: str = "INR"


class CheckoutVerificationRequest(BaseModel):
    razorpay_payment_id: str
    razorpay_subscription_id: str
    razorpay_signature: str


class CheckoutVerificationResponse(BaseModel):
    verified: bool
    subscription_status: SubscriptionStatus


class WebhookResponse(BaseModel):
    accepted: bool
    duplicate: bool


class BillingSubscription(BaseModel):
    provider_subscription_id: str
    plan: PlanCode
    interval: BillingInterval
    status: SubscriptionStatus
    next_renewal: datetime | None = None
    provider: str = "razorpay"


class PaymentSummary(BaseModel):
    provider_payment_id: str
    amount_paise: int | None
    currency: str
    status: str
    created_at: datetime


class BillingAccount(BaseModel):
    plan: PlanCode
    subscription_status: SubscriptionStatus
    subscription: BillingSubscription | None
    payments: list[PaymentSummary]
    mode: str


class BillingActionResponse(BaseModel):
    accepted: bool
    provider_status: str


subscription_store = SubscriptionStateStore()


@router.get("/account", response_model=BillingAccount)
def billing_account(user: Annotated[User, Depends(current_user)]) -> BillingAccount:
    record = subscription_store.get_for_user(user.id)
    subscription = None
    if record is not None:
        renewal = None
        if postgres_store is not None:
            row = postgres_store.get_subscription(record.provider_subscription_id)
            renewal = row.get("current_period_end") if row else None
        subscription = BillingSubscription(
            provider_subscription_id=record.provider_subscription_id,
            plan=record.plan,
            interval=record.interval,
            status=record.status,
            next_renewal=renewal,
        )
    payment_rows = postgres_store.list_payments(user.id) if postgres_store is not None else []
    return BillingAccount(
        plan=user.plan,
        subscription_status=user.subscription_status,
        subscription=subscription,
        payments=[PaymentSummary.model_validate(row) for row in payment_rows],
        mode=settings.razorpay_mode,
    )


def verify_checkout_signature(
    *, payment_id: str, subscription_id: str, signature: str, secret: str
) -> bool:
    message = f"{payment_id}|{subscription_id}".encode()
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(*, body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _plan_id(plan: PlanCode, interval: BillingInterval) -> str:
    key = f"RAZORPAY_PLAN_{plan.value}_{interval.value}"
    return os.getenv(key, "")


def _amount_paise(plan: PlanCode, interval: BillingInterval) -> int:
    definition = PLAN_CATALOG[plan]
    return (
        definition.monthly_price_paise
        if interval is BillingInterval.MONTHLY
        else definition.annual_price_paise
    )


def _require_test_configuration() -> None:
    if settings.razorpay_mode != "test":
        raise HTTPException(
            status_code=503,
            detail="Live charging is safety-gated and requires explicit owner activation.",
        )
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise HTTPException(status_code=503, detail="Razorpay Test Mode is not configured.")


def _require_private_test_operator(user: User) -> None:
    if SpecialRole.ADMIN not in user.roles:
        raise HTTPException(
            status_code=403,
            detail="Paid plans are coming soon; Test checkout is not available to public accounts.",
        )
    _require_test_configuration()


@router.post("/subscriptions", response_model=CheckoutResponse)
def create_subscription(
    payload: CheckoutRequest,
    user: Annotated[User, Depends(current_user)],
) -> CheckoutResponse:
    _require_private_test_operator(user)
    if payload.plan is PlanCode.FREE:
        raise HTTPException(status_code=422, detail="The Free plan does not use checkout.")
    provider_plan_id = _plan_id(payload.plan, payload.interval)
    if not provider_plan_id:
        raise HTTPException(status_code=503, detail="Requested Razorpay plan mapping is missing.")
    try:
        response = httpx.post(
            "https://api.razorpay.com/v1/subscriptions",
            auth=(settings.razorpay_key_id, settings.razorpay_key_secret),
            json={"plan_id": provider_plan_id, "total_count": 120, "quantity": 1},
            timeout=15,
        )
        response.raise_for_status()
        provider_payload: dict[str, Any] = response.json()
        subscription_id = str(provider_payload["id"])
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=502, detail="Razorpay subscription creation failed."
        ) from exc
    subscription_store.add(
        SubscriptionRecord(
            user_id=user.id,
            plan=payload.plan,
            interval=payload.interval,
            provider_subscription_id=subscription_id,
            status=SubscriptionStatus.CREATED,
        )
    )
    return CheckoutResponse(
        key_id=settings.razorpay_key_id,
        subscription_id=subscription_id,
        plan=payload.plan,
        interval=payload.interval,
        amount_paise=_amount_paise(payload.plan, payload.interval),
    )


@router.post("/verify", response_model=CheckoutVerificationResponse)
def verify_checkout(
    payload: CheckoutVerificationRequest,
    user: Annotated[User, Depends(current_user)],
) -> CheckoutVerificationResponse:
    _require_private_test_operator(user)
    record = subscription_store.get(payload.razorpay_subscription_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(status_code=404, detail="Subscription not found.")
    verified = verify_checkout_signature(
        payment_id=payload.razorpay_payment_id,
        subscription_id=payload.razorpay_subscription_id,
        signature=payload.razorpay_signature,
        secret=settings.razorpay_key_secret,
    )
    if not verified:
        raise HTTPException(status_code=400, detail="Invalid Razorpay checkout signature.")
    if postgres_store is not None:
        postgres_store.upsert_payment(
            provider_payment_id=payload.razorpay_payment_id,
            provider_subscription_id=payload.razorpay_subscription_id,
            amount_paise=_amount_paise(record.plan, record.interval),
            currency="INR",
            status="AUTHENTICATING",
        )
    subscription_store.apply_event(
        f"checkout:{payload.razorpay_payment_id}",
        payload.razorpay_subscription_id,
        SubscriptionStatus.AUTHENTICATING,
    )
    return CheckoutVerificationResponse(
        verified=True,
        subscription_status=SubscriptionStatus.AUTHENTICATING,
    )


@router.post(
    "/subscriptions/{provider_subscription_id}/cancel", response_model=BillingActionResponse
)
def cancel_subscription(
    provider_subscription_id: str,
    user: Annotated[User, Depends(current_user)],
) -> BillingActionResponse:
    return _subscription_action(
        provider_subscription_id,
        user,
        action="cancel",
        body={"cancel_at_cycle_end": True},
    )


@router.post(
    "/subscriptions/{provider_subscription_id}/resume", response_model=BillingActionResponse
)
def resume_subscription(
    provider_subscription_id: str,
    user: Annotated[User, Depends(current_user)],
) -> BillingActionResponse:
    return _subscription_action(
        provider_subscription_id,
        user,
        action="resume",
        body={"resume_at": "now"},
    )


def _subscription_action(
    provider_subscription_id: str,
    user: User,
    *,
    action: str,
    body: dict[str, bool | str],
) -> BillingActionResponse:
    _require_private_test_operator(user)
    record = subscription_store.get(provider_subscription_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(status_code=404, detail="Subscription not found.")
    try:
        response = httpx.post(
            f"https://api.razorpay.com/v1/subscriptions/{provider_subscription_id}/{action}",
            auth=(settings.razorpay_key_id, settings.razorpay_key_secret),
            json=body,
            timeout=15,
        )
        response.raise_for_status()
        provider_status = str(response.json()["status"])
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Razorpay {action} request failed.") from exc
    subscription_store.apply_event(
        f"owner:{action}:{uuid4().hex}",
        provider_subscription_id,
        _provider_status(provider_status),
        event_type=f"owner.subscription.{action}",
        provider_created_at=datetime.now(UTC),
    )
    return BillingActionResponse(accepted=True, provider_status=provider_status)


@router.post("/webhooks/razorpay", response_model=WebhookResponse)
async def razorpay_webhook(
    request: Request,
    signature: Annotated[str | None, Header(alias="X-Razorpay-Signature")] = None,
    event_header: Annotated[str | None, Header(alias="X-Razorpay-Event-Id")] = None,
) -> WebhookResponse:
    body = await _read_limited_body(request, settings.razorpay_webhook_max_bytes)
    if not settings.razorpay_webhook_secret:
        raise HTTPException(status_code=503, detail="Razorpay webhook is not configured.")
    if not signature or not verify_webhook_signature(
        body=body, signature=signature, secret=settings.razorpay_webhook_secret
    ):
        raise HTTPException(status_code=400, detail="Invalid Razorpay webhook signature.")
    try:
        payload: dict[str, Any] = json.loads(body)
        event_type = str(payload["event"])
        entity = payload["payload"]["subscription"]["entity"]
        provider_subscription_id = str(entity["id"])
        provider_created_raw = payload["created_at"]
        if not isinstance(provider_created_raw, int):
            raise TypeError("Webhook created_at must be an integer")
        provider_created_at = datetime.fromtimestamp(provider_created_raw, UTC)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Malformed Razorpay webhook.") from exc
    payload_digest = hashlib.sha256(body).hexdigest()
    # The provider event header is not covered by Razorpay's body HMAC. Deduplicate
    # exclusively on the signed bytes so header rotation cannot replay an old body.
    event_id = payload_digest
    status = _webhook_status(event_type)
    accepted = subscription_store.apply_event(
        event_id,
        provider_subscription_id,
        status,
        event_type=event_type,
        payload_sha256=payload_digest,
        current_period_end=(
            datetime.fromtimestamp(entity["current_end"], UTC)
            if isinstance(entity.get("current_end"), int)
            else None
        ),
        provider_created_at=provider_created_at,
    )
    payment_entity = payload.get("payload", {}).get("payment", {}).get("entity")
    if accepted and postgres_store is not None and isinstance(payment_entity, dict):
        payment_id = payment_entity.get("id")
        if payment_id:
            amount = payment_entity.get("amount")
            postgres_store.upsert_payment(
                provider_payment_id=str(payment_id),
                provider_subscription_id=provider_subscription_id,
                amount_paise=int(amount) if isinstance(amount, int) else None,
                currency=str(payment_entity.get("currency") or "INR"),
                status=str(payment_entity.get("status") or status.value),
            )
    return WebhookResponse(accepted=True, duplicate=not accepted)


def _webhook_status(event_type: str) -> SubscriptionStatus:
    mapping = {
        "subscription.authenticated": SubscriptionStatus.AUTHENTICATING,
        "subscription.activated": SubscriptionStatus.ACTIVE,
        "subscription.charged": SubscriptionStatus.ACTIVE,
        "subscription.pending": SubscriptionStatus.PAST_DUE,
        "subscription.halted": SubscriptionStatus.PAST_DUE,
        "subscription.paused": SubscriptionStatus.PAUSED,
        "subscription.resumed": SubscriptionStatus.ACTIVE,
        "subscription.cancelled": SubscriptionStatus.CANCELLED,
        "subscription.completed": SubscriptionStatus.EXPIRED,
    }
    return mapping.get(event_type, SubscriptionStatus.CREATED)


def _provider_status(provider_status: str) -> SubscriptionStatus:
    mapping = {
        "created": SubscriptionStatus.CREATED,
        "authenticated": SubscriptionStatus.AUTHENTICATING,
        "active": SubscriptionStatus.ACTIVE,
        "pending": SubscriptionStatus.PAST_DUE,
        "halted": SubscriptionStatus.PAST_DUE,
        "paused": SubscriptionStatus.PAUSED,
        "cancelled": SubscriptionStatus.CANCELLED,
        "completed": SubscriptionStatus.EXPIRED,
        "expired": SubscriptionStatus.EXPIRED,
    }
    return mapping.get(provider_status.casefold(), SubscriptionStatus.CREATED)
