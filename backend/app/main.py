from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import router

app = FastAPI(
    title="NutriLens AI Backend",
    description="Backend API for food-label OCR and nutrition analysis.",
    version="0.1.0",
)

app.include_router(router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "NutriLens AI backend",
    }
