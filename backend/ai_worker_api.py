"""Private, token-authenticated R3 inference worker entry point.

The worker deliberately owns no NutriLens user data, sessions, billing state,
or database connection. The business API validates and authorizes uploads,
then sends bounded image bytes over an authenticated internal channel.
"""

from __future__ import annotations

import asyncio
import hmac
from typing import Annotated

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile, status

from ai.food_understanding.pipeline import FoodUnderstandingPipeline, ImagePayload
from ai.food_understanding.schemas import InputKind, R3ScanResult, ViewType
from backend.settings import settings

app = FastAPI(title="NutriLens X private AI worker", docs_url=None, redoc_url=None)
pipeline = FoodUnderstandingPipeline()
CAPACITY_ERROR_HEADER = "X-NutriLens-Worker-Error"
CAPACITY_ERROR_VALUE = "capacity-full"
# This module is loaded once per worker process. The one-slot gate protects the
# bounded CPU/RAM inference process from overlapping OCR/detector allocations;
# it intentionally is not shared across API instances or hosts.
_inference_slots = asyncio.BoundedSemaphore(settings.ai_worker_max_concurrent_scans)


def _require_internal_token(authorization: str | None) -> None:
    expected = settings.ai_worker_token
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not expected or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized worker call.",
        )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "nutrilens-ai-worker"}


@app.post("/internal/r3/scan", response_model=R3ScanResult)
async def scan(
    files: Annotated[list[UploadFile], File()],
    input_kind: Annotated[str, Form()],
    view_types: Annotated[str, Form()],
    languages: Annotated[str, Form()] = "en",
    trace_id: Annotated[str, Form()] = "",
    authorization: Annotated[str | None, Header()] = None,
) -> R3ScanResult:
    _require_internal_token(authorization)
    if not 1 <= len(files) <= 5:
        raise HTTPException(status_code=422, detail="A scan needs between one and five images.")
    try:
        parsed_kind = InputKind(input_kind)
        parsed_views = [ViewType(value) for value in view_types.split(",") if value]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid scan request.") from exc
    if len(parsed_views) != len(files):
        raise HTTPException(status_code=422, detail="One view type is required per image.")
    contents = await asyncio.gather(
        *(upload.read(settings.r3_max_upload_bytes + 1) for upload in files)
    )
    await asyncio.gather(*(upload.close() for upload in files))
    if any(len(content) > settings.r3_max_upload_bytes for content in contents):
        raise HTTPException(status_code=413, detail="Image exceeds the configured upload limit.")
    payloads = [
        ImagePayload(
            content=content,
            filename=upload.filename or "upload.bin",
            mime_type=upload.content_type or "application/octet-stream",
            view_type=parsed_views[index],
        )
        for index, (upload, content) in enumerate(zip(files, contents, strict=True))
    ]
    acquired = False
    try:
        try:
            await asyncio.wait_for(
                _inference_slots.acquire(), timeout=settings.ai_worker_queue_timeout_seconds
            )
        except TimeoutError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI worker capacity is temporarily full. Please retry shortly.",
                headers={
                    CAPACITY_ERROR_HEADER: CAPACITY_ERROR_VALUE,
                    "Retry-After": "2",
                },
            ) from exc
        acquired = True
        return await asyncio.wait_for(
            asyncio.to_thread(
                pipeline.scan,
                payloads,
                input_kind=parsed_kind,
                languages=[value.strip() for value in languages.split(",") if value.strip()]
                or ["en"],
                trace_id=trace_id or None,
            ),
            timeout=settings.r3_scan_timeout_seconds,
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="AI worker timed out.") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail="The image could not be processed.") from exc
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - third-party inference boundary
        raise HTTPException(status_code=503, detail="AI worker inference is unavailable.") from exc
    finally:
        if acquired:
            _inference_slots.release()
