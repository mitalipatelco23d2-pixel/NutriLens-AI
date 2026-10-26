"""Central plan catalogue and backend-authoritative entitlement resolution."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field


class PlanCode(StrEnum):
    FREE = "FREE"
    PLUS = "PLUS"
    PRO = "PRO"
    MAX = "MAX"


class BillingInterval(StrEnum):
    MONTHLY = "MONTHLY"
    ANNUAL = "ANNUAL"


class SpecialRole(StrEnum):
    DEMO = "DEMO"
    RESEARCHER = "RESEARCHER"
    ADMIN = "ADMIN"


class SubscriptionStatus(StrEnum):
    FREE = "FREE"
    CREATED = "CREATED"
    AUTHENTICATING = "AUTHENTICATING"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


EntitlementValue = int | bool


class PlanDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: PlanCode
    display_name: str
    monthly_price_paise: int = Field(ge=0)
    annual_price_paise: int = Field(ge=0)
    most_popular: bool = False
    entitlements: dict[str, EntitlementValue]


class EffectiveEntitlements(BaseModel):
    plan: PlanCode
    subscription_status: SubscriptionStatus
    roles: set[SpecialRole]
    values: dict[str, EntitlementValue]
    override_source: str | None = None


BASE_ENTITLEMENTS: Final[dict[str, EntitlementValue]] = {
    "safety.allergens": True,
    "safety.additives": True,
    "safety.evidence": True,
    "scan.monthly_limit": 10,
    "assistant.daily_limit": 5,
    "analytics.history_days": 7,
    "diary.history_days": 30,
    "pantry.max_items": 25,
    "personalization.advanced": False,
    "recommendations.advanced": False,
    "explanations.advanced": False,
    "export.enabled": False,
    "research.enabled": False,
    "admin.enabled": False,
}


def _with_base(**overrides: EntitlementValue) -> dict[str, EntitlementValue]:
    return {**BASE_ENTITLEMENTS, **overrides}


PLAN_CATALOG: Final[dict[PlanCode, PlanDefinition]] = {
    PlanCode.FREE: PlanDefinition(
        code=PlanCode.FREE,
        display_name="Free",
        monthly_price_paise=0,
        annual_price_paise=0,
        entitlements=_with_base(),
    ),
    PlanCode.PLUS: PlanDefinition(
        code=PlanCode.PLUS,
        display_name="Plus",
        monthly_price_paise=7_900,
        annual_price_paise=79_900,
        entitlements=_with_base(
            **{
                "scan.monthly_limit": 100,
                "assistant.daily_limit": 30,
                "analytics.history_days": 90,
                "diary.history_days": 365,
                "pantry.max_items": 150,
            }
        ),
    ),
    PlanCode.PRO: PlanDefinition(
        code=PlanCode.PRO,
        display_name="Pro",
        monthly_price_paise=14_900,
        annual_price_paise=149_900,
        most_popular=True,
        entitlements=_with_base(
            **{
                "scan.monthly_limit": 300,
                "assistant.daily_limit": 100,
                "analytics.history_days": 730,
                "diary.history_days": 1_825,
                "pantry.max_items": 500,
                "personalization.advanced": True,
                "recommendations.advanced": True,
                "explanations.advanced": True,
            }
        ),
    ),
    PlanCode.MAX: PlanDefinition(
        code=PlanCode.MAX,
        display_name="Max",
        monthly_price_paise=24_900,
        annual_price_paise=249_900,
        entitlements=_with_base(
            **{
                "scan.monthly_limit": 1_000,
                "assistant.daily_limit": 300,
                "analytics.history_days": 3_650,
                "diary.history_days": 3_650,
                "pantry.max_items": 2_000,
                "personalization.advanced": True,
                "recommendations.advanced": True,
                "explanations.advanced": True,
                "export.enabled": True,
            }
        ),
    ),
}


def resolve_entitlements(
    plan: PlanCode,
    subscription_status: SubscriptionStatus,
    roles: set[SpecialRole] | None = None,
) -> EffectiveEntitlements:
    """Resolve effective access; inactive paid plans safely fall back to Free."""

    assigned_roles = roles or set()
    effective_plan = (
        plan
        if plan is PlanCode.FREE or subscription_status is SubscriptionStatus.ACTIVE
        else PlanCode.FREE
    )
    values = dict(PLAN_CATALOG[effective_plan].entitlements)
    override_source: str | None = None

    if SpecialRole.ADMIN in assigned_roles:
        values = _full_access(research=True, admin=True)
        override_source = SpecialRole.ADMIN
    elif SpecialRole.DEMO in assigned_roles:
        values = _full_access(research=True, admin=False)
        override_source = SpecialRole.DEMO
    elif SpecialRole.RESEARCHER in assigned_roles:
        values["research.enabled"] = True
        override_source = SpecialRole.RESEARCHER

    return EffectiveEntitlements(
        plan=effective_plan,
        subscription_status=subscription_status,
        roles=assigned_roles,
        values=values,
        override_source=override_source,
    )


def _full_access(*, research: bool, admin: bool) -> dict[str, EntitlementValue]:
    values = dict(PLAN_CATALOG[PlanCode.MAX].entitlements)
    values.update(
        {
            "scan.monthly_limit": 10_000,
            "assistant.daily_limit": 2_000,
            "research.enabled": research,
            "admin.enabled": admin,
        }
    )
    return values
