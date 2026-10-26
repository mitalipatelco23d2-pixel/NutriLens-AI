from backend.entitlements import (
    PLAN_CATALOG,
    PlanCode,
    SpecialRole,
    SubscriptionStatus,
    resolve_entitlements,
)


def test_frozen_plan_prices_are_stored_in_paise() -> None:
    assert PLAN_CATALOG[PlanCode.PLUS].monthly_price_paise == 7_900
    assert PLAN_CATALOG[PlanCode.PLUS].annual_price_paise == 79_900
    assert PLAN_CATALOG[PlanCode.PRO].monthly_price_paise == 14_900
    assert PLAN_CATALOG[PlanCode.PRO].annual_price_paise == 149_900
    assert PLAN_CATALOG[PlanCode.MAX].monthly_price_paise == 24_900
    assert PLAN_CATALOG[PlanCode.MAX].annual_price_paise == 249_900
    assert PLAN_CATALOG[PlanCode.PRO].most_popular is True


def test_inactive_paid_subscription_falls_back_to_free_limits() -> None:
    result = resolve_entitlements(PlanCode.PRO, SubscriptionStatus.PAST_DUE)

    assert result.plan is PlanCode.FREE
    assert result.values["scan.monthly_limit"] == 10
    assert result.values["safety.allergens"] is True


def test_demo_role_gets_full_product_without_frontend_flag() -> None:
    result = resolve_entitlements(
        PlanCode.FREE,
        SubscriptionStatus.FREE,
        {SpecialRole.DEMO},
    )

    assert result.values["personalization.advanced"] is True
    assert result.values["research.enabled"] is True
    assert result.values["admin.enabled"] is False
    assert result.override_source == "DEMO"


def test_researcher_access_does_not_grant_admin() -> None:
    result = resolve_entitlements(
        PlanCode.FREE,
        SubscriptionStatus.FREE,
        {SpecialRole.RESEARCHER},
    )

    assert result.values["research.enabled"] is True
    assert result.values["admin.enabled"] is False
