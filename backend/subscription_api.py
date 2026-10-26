"""Public plan catalogue and entitlement contracts."""

from __future__ import annotations

from fastapi import APIRouter

from backend.entitlements import PLAN_CATALOG, PlanDefinition

router = APIRouter(prefix="/api/v1/subscriptions", tags=["Subscriptions"])


@router.get("/plans", response_model=list[PlanDefinition])
def list_plans() -> list[PlanDefinition]:
    """Return the canonical pricing and plan-feature catalogue."""

    return list(PLAN_CATALOG.values())
