from __future__ import annotations

import logging

from .api.auth_routes import router as auth_router

from .api.user_routes import router as user_router

from .db.init_db import init_db

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import legacy_router, router
from .core.config import get_settings
from .core.errors import NutriLensError
from .core.logging import configure_logging

logger = logging.getLogger(__name__)


def _error_response(status_code: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "error",
            "error": {"code": code, "message": message, "details": details},
        },
    )


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    init_db()
    application = FastAPI(
        title="NutriLens AI",
        description="Nutrition-label OCR and backend integration API",
        version="1.0.0",
    )
    if settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization"],
        )

    @application.exception_handler(NutriLensError)
    async def handle_application_error(_: Request, exc: NutriLensError) -> JSONResponse:
        logger.warning("Request failed with %s", exc.code)
        return _error_response(exc.status_code, exc.code, exc.public_message)

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        safe_errors = [
            {"location": list(item["loc"]), "message": item["msg"], "type": item["type"]}
            for item in exc.errors()
        ]
        return _error_response(422, "validation_error", "Request validation failed.", {"errors": safe_errors})

    @application.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unexpected request failure", exc_info=exc)
        return _error_response(500, "internal_error", "An unexpected server error occurred.")

    application.include_router(router)
    application.include_router(auth_router)
    application.include_router(user_router)
    application.include_router(legacy_router)

    if settings.frontend_dir.is_dir():
        application.mount("/static", StaticFiles(directory=settings.frontend_dir), name="static")

    @application.get("/", include_in_schema=False)
    def home():
        index_path = settings.frontend_dir / "index.html"
        if index_path.is_file():
            return FileResponse(index_path)
        return {"service": "NutriLens AI", "docs": "/docs", "api": "/api/v1"}

    return application


app = create_app()
