from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.auth import router as auth_router
from backend.auth import validate_security_settings
from backend.custom_recipe_actions_api import router as custom_recipe_actions_router
from backend.custom_recipes_api import router as custom_recipes_router
from backend.hydration_api import router as hydration_router
from backend.knowledge_api import router as knowledge_router
from backend.model_registry_api import router as model_registry_router
from backend.payments import router as payment_router
from backend.population_api import router as population_router
from backend.product_api import router as product_router
from backend.r3_api import router as r3_router
from backend.r4_api import router as r4_router
from backend.scan_jobs import dispatcher
from backend.security import (
    OperationalLoggingMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from backend.service_health import collect_service_health
from backend.settings import settings
from backend.storage_runtime import migrate_if_configured
from backend.subscription_api import router as subscription_router
from backend.weight_api import router as weight_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await dispatcher.start()
    try:
        yield
    finally:
        await dispatcher.stop()


app = FastAPI(
    title="NutriLens X API",
    version="1.0.0",
    description="Evidence-oriented food intelligence and wellness decision support.",
    lifespan=lifespan,
)
validate_security_settings(settings)
migrate_if_configured()
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    RateLimitMiddleware,
    backend=settings.rate_limit_backend,
    redis_url=settings.redis_url,
    fail_closed=settings.app_environment != "development",
)
app.add_middleware(OperationalLoggingMiddleware)
app.include_router(r3_router)
app.include_router(r4_router)
app.include_router(knowledge_router)
app.include_router(model_registry_router)
app.include_router(subscription_router)
app.include_router(auth_router)
app.include_router(payment_router)
app.include_router(product_router)
app.include_router(hydration_router)
app.include_router(weight_router)
app.include_router(custom_recipes_router)
app.include_router(custom_recipe_actions_router)
app.include_router(population_router)


@app.get("/api/v1/health")
def readiness() -> dict[str, object]:
    services = collect_service_health(settings)
    return {
        "status": "healthy"
        if all(value == "healthy" for value in services.values())
        else "degraded",
        "environment": settings.app_environment,
        "services": services,
    }


@app.get("/health")
def liveness() -> dict[str, object]:
    # Render supplies the deployed Git SHA; never echo arbitrary environment data.
    revision = os.getenv("RENDER_GIT_COMMIT", "").strip().lower()
    return {
        "status": "healthy",
        "environment": settings.app_environment,
        "services": {"api": "healthy"},
        "source_revision": revision if re.fullmatch(r"[0-9a-f]{40}", revision) else None,
    }
