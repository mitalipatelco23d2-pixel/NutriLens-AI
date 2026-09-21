from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router


# ============================================================
# FASTAPI APPLICATION
# ============================================================

app = FastAPI(
    title="NutriLens AI Backend",
    description=(
        "Backend API for food-label OCR, nutrition analysis, "
        "ingredient risk prediction, XAI, and recommendations."
    ),
    version="1.0.0",
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# API ROUTES
# ============================================================

app.include_router(router)


# ============================================================
# ROOT ENDPOINT
# ============================================================

@app.get("/")
def root() -> dict[str, str]:
    """
    Basic backend information endpoint.
    """

    return {
        "service": "NutriLens AI Backend",
        "status": "running",
        "version": "1.0.0",
    }


# ============================================================
# BACKWARD-COMPATIBILITY HEALTH ENDPOINT
# ============================================================

@app.get("/health")
def health_check() -> dict[str, str]:
    """
    Backward-compatible health endpoint.

    The main API health endpoint is:
        /api/v1/health
    """

    return {
        "status": "ok",
        "service": "NutriLens AI Backend",
    }
