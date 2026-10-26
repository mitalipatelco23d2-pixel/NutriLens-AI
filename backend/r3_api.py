"""FastAPI routes for the R3 local Food Understanding Engine."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, date, datetime
from hashlib import sha256
from threading import RLock
from time import perf_counter
from typing import Annotated
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, ValidationError

from ai.food_understanding.image_input import (
    ImageInputError,
    encoded_pixel_count,
    validate_image_bytes,
)
from ai.food_understanding.pipeline import FoodUnderstandingPipeline, ImagePayload
from ai.food_understanding.schemas import (
    CorrectionRequest,
    ErrorResponse,
    InputKind,
    R3ScanResult,
    ViewType,
)
from ai.food_understanding.store import EphemeralScanStore, ScanNotFoundError
from backend.ai_worker_client import RemoteAIWorkerError, run_remote_scan
from backend.auth import User, current_user, optional_current_user
from backend.client_evidence_gate import (
    ClientEvidenceDecision,
    ClientEvidenceGatePolicy,
    classify_client_evidence,
)
from backend.client_inference_contract import (
    AndroidClientInferenceMode,
    ClientEvidenceClassification,
    ClientEvidenceValidation,
    ClientInferenceCapabilities,
    ClientOcrEvidence,
    client_inference_capabilities,
    validate_client_evidence,
)
from backend.client_structured_result import build_client_structured_result
from backend.entitlements import resolve_entitlements
from backend.postgres_store import ScanJobQuotaExceeded
from backend.scan_jobs import dispatcher
from backend.settings import settings
from backend.storage_runtime import postgres_store

router = APIRouter(prefix="/api/v1/scan", tags=["R3 Food Understanding"])
logger = logging.getLogger(__name__)
pipeline = FoodUnderstandingPipeline()
scan_store = EphemeralScanStore()
_scan_usage: dict[tuple[str, date], int] = {}
_scan_usage_lock = RLock()


class ScanHistoryItem(BaseModel):
    scan_id: str
    created_at: datetime
    input_kind: InputKind
    status: str
    product_name: str | None
    brand: str | None
    confidence: float | None


class ScanJobStatus(BaseModel):
    job_id: str
    status: str
    input_kind: InputKind
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: R3ScanResult | None = None
    error_code: str | None = None
    error_message: str | None = None
    client_evidence_decision: str | None = None
    client_evidence_reasons: list[str] = []
    server_fallback_required: bool | None = None


async def _read_upload(upload: UploadFile) -> bytes:
    content = await upload.read(settings.r3_max_upload_bytes + 1)
    await upload.close()
    if len(content) > settings.r3_max_upload_bytes:
        raise ImageInputError(
            "FILE_TOO_LARGE", f"Image exceeds the {settings.r3_max_upload_bytes}-byte limit."
        )
    return content


async def _run(
    uploads: list[UploadFile],
    *,
    input_kind: InputKind,
    view_types: list[ViewType],
    languages: list[str],
    user: User | None,
) -> R3ScanResult:
    trace_id = f"trace-{uuid4().hex}"
    reserved = False
    dispatched = False
    try:
        _reserve_scan(user)
        reserved = user is not None
        payloads = [
            ImagePayload(
                content=await _read_upload(upload),
                filename=upload.filename or "upload.bin",
                mime_type=upload.content_type or "application/octet-stream",
                view_type=view_types[index],
            )
            for index, upload in enumerate(uploads)
        ]
        total_pixels = sum(encoded_pixel_count(payload.content) for payload in payloads)
        if total_pixels > pipeline.config.max_product_pixels:
            raise ImageInputError(
                "TOO_MANY_PRODUCT_PIXELS",
                f"Combined views exceed the {pipeline.config.max_product_pixels}-pixel limit.",
            )
        task = asyncio.create_task(
            run_remote_scan(
                payloads,
                input_kind=input_kind,
                languages=languages,
                trace_id=trace_id,
            )
            if settings.ai_worker_url
            else asyncio.to_thread(
                pipeline.scan,
                payloads,
                input_kind=input_kind,
                languages=languages,
                trace_id=trace_id,
            )
        )
        dispatched = True
        result = await asyncio.wait_for(
            asyncio.shield(task), timeout=settings.r3_scan_timeout_seconds
        )
        if postgres_store is not None and user is not None:
            postgres_store.put_scan(user.id, result.scan_id, result.model_dump(mode="json"))
            return result
        return scan_store.save(result, owner_id=user.id if user is not None else None)
    except asyncio.CancelledError:
        if reserved and not dispatched:
            _release_scan_reservation(user)
        raise
    except ImageInputError as exc:
        if reserved:
            _release_scan_reservation(user)
        _raise_error(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.code, str(exc), trace_id)
    except TimeoutError:
        _raise_error(
            status.HTTP_504_GATEWAY_TIMEOUT,
            "SCAN_TIMEOUT",
            "The local scan exceeded its configured processing timeout.",
            trace_id,
            retryable=True,
        )
    except RemoteAIWorkerError:
        _raise_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "AI_WORKER_UNAVAILABLE",
            "Enhanced scan is temporarily unavailable. Please try a clearer photo or retry later.",
            trace_id,
            retryable=True,
        )
    except ValueError as exc:
        if reserved:
            _release_scan_reservation(user)
        _raise_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "INVALID_SCAN", str(exc), trace_id)
    except HTTPException:
        raise
    except Exception as exc:
        _raise_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "SCAN_FAILED",
            f"Local scan failed safely ({type(exc).__name__}).",
            trace_id,
            retryable=True,
        )
    raise AssertionError("unreachable")


def _raise_error(
    status_code: int,
    code: str,
    message: str,
    trace_id: str,
    *,
    retryable: bool = False,
) -> None:
    error = ErrorResponse(error_code=code, message=message, trace_id=trace_id, retryable=retryable)
    raise HTTPException(status_code=status_code, detail=error.model_dump(mode="json"))


async def _create_scan_job(
    uploads: list[UploadFile],
    *,
    input_kind: InputKind,
    view_types: list[ViewType],
    languages: list[str],
    user: User,
    idempotency_key: str | None,
    evidence_json: str | None = None,
) -> ScanJobStatus:
    if postgres_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Durable scan processing is temporarily unavailable.",
        )
    if len(uploads) != len(view_types) or not uploads:
        raise HTTPException(status_code=422, detail="One view type is required per image.")
    payloads = [
        ImagePayload(
            content=await _read_upload(upload),
            filename=upload.filename or "upload.bin",
            mime_type=upload.content_type or "application/octet-stream",
            view_type=view_types[index],
        )
        for index, upload in enumerate(uploads)
    ]
    total_pixels = sum(encoded_pixel_count(payload.content) for payload in payloads)
    if total_pixels > pipeline.config.max_product_pixels:
        raise HTTPException(
            status_code=422,
            detail="Combined views exceed the configured product-image pixel limit.",
        )
    request_identity = idempotency_key.strip() if idempotency_key else ""
    if not request_identity:
        digest = sha256()
        digest.update(input_kind.value.encode())
        for payload in payloads:
            digest.update(payload.view_type.value.encode())
            digest.update(payload.mime_type.encode())
            digest.update(payload.content)
        request_identity = digest.hexdigest()
    elif len(request_identity) > 128:
        raise HTTPException(status_code=422, detail="Idempotency key is too long.")
    normalized_key = sha256(request_identity.encode()).hexdigest()
    completed_result: R3ScanResult | None = None
    evidence_decision: str | None = None
    evidence_reasons: list[str] = []
    if evidence_json is not None:
        completed_result, evidence_decision, evidence_reasons = await asyncio.to_thread(
            _prepare_client_job_result, evidence_json, payloads, input_kind, user.id
        )
    allowance = int(
        resolve_entitlements(user.plan, user.subscription_status, set(user.roles)).values[
            "scan.monthly_limit"
        ]
    )
    now = datetime.now(UTC)
    try:
        record, created = await asyncio.to_thread(
            postgres_store.create_scan_job,
            user_id=user.id,
            idempotency_key=normalized_key,
            input_kind=input_kind.value,
            view_types=[view.value for view in view_types],
            languages=languages,
            images=(
                []
                if completed_result
                else [
                    (payload.filename, payload.mime_type, payload.content) for payload in payloads
                ]
            ),
            period_start=date(now.year, now.month, 1),
            monthly_limit=allowance,
            **({"completed_result": completed_result} if completed_result else {}),
        )
    except ScanJobQuotaExceeded as exc:
        raise HTTPException(status_code=429, detail="Monthly scan allowance reached.") from exc
    if created and record["status"] == "QUEUED":
        await dispatcher.enqueue(str(record["job_id"]))
    response = _scan_job_status(record, user)
    if evidence_json is not None and response.server_fallback_required is None:
        response.client_evidence_decision = (
            evidence_decision if created else ClientEvidenceDecision.FALLBACK_REQUIRED.value
        )
        response.client_evidence_reasons = (
            evidence_reasons if created else ["EXISTING_SERVER_JOB_REUSED_AS_STORED"]
        )
        response.server_fallback_required = True
    return response


def _prepare_client_job_result(
    evidence_json: str, payloads: list[ImagePayload], input_kind: InputKind, user_id: str
) -> tuple[R3ScanResult | None, str, list[str]]:
    """Never trusts client fields as entitlement, identity, or model-execution proof."""
    fallback = ClientEvidenceDecision.FALLBACK_REQUIRED.value
    capabilities = client_inference_capabilities(settings.android_client_inference_mode)
    mode = capabilities.android_mode
    if mode is not AndroidClientInferenceMode.PREFERRED:
        return None, fallback, ["PREFERRED_ROLLOUT_NOT_ENABLED"]
    if user_id not in settings.android_client_preferred_user_ids:
        return None, fallback, ["OWNER_NOT_IN_PREFERRED_ROLLOUT"]
    if len(payloads) != 1 or input_kind not in {InputKind.IMAGE, InputKind.PRODUCT, InputKind.OCR}:
        return None, fallback, ["UNSUPPORTED_CLIENT_SCAN_KIND_OR_VIEW_COUNT"]
    if len(evidence_json.encode("utf-8")) > 512_000:
        return None, ClientEvidenceDecision.INVALID.value, ["CLIENT_EVIDENCE_PAYLOAD_TOO_LARGE"]
    started = perf_counter()
    try:
        evidence = ClientOcrEvidence.model_validate_json(evidence_json)
    except ValidationError:
        return None, ClientEvidenceDecision.INVALID.value, ["CLIENT_EVIDENCE_SCHEMA_INVALID"]
    payload = payloads[0]
    try:
        validated = validate_image_bytes(
            payload.content,
            filename=payload.filename,
            mime_type=payload.mime_type,
            view_id="client-android-ocr",
            view_type=payload.view_type,
            config=pipeline.config,
        )
    except ImageInputError as exc:
        return None, ClientEvidenceDecision.INVALID.value, [f"SOURCE_IMAGE_{exc.code}"]
    if validated.metadata.exif_orientation_applied:
        return None, fallback, ["EXIF_ORIENTATION_REQUIRES_SERVER_FALLBACK"]
    validation_ms = (perf_counter() - started) * 1000
    extraction_started = perf_counter()
    gate = classify_client_evidence(
        evidence,
        verified_image_sha256=validated.metadata.sha256,
        verified_image_width=validated.metadata.width,
        verified_image_height=validated.metadata.height,
        rollout_mode=mode,
        policy=ClientEvidenceGatePolicy(
            min_positioned_lines=settings.android_client_min_positioned_lines,
            min_positioned_ratio=settings.android_client_min_positioned_ratio,
            min_nutrition_rows=settings.android_client_min_nutrition_rows,
            min_major_nutrients=settings.android_client_min_major_nutrients,
            min_nutrition_confidence=settings.android_client_min_nutrition_confidence,
        ),
    )
    if gate.decision is not ClientEvidenceDecision.ACCEPTED:
        return None, gate.decision.value, list(gate.reasons)
    result = build_client_structured_result(
        evidence,
        gate,
        validated.metadata,
        input_kind=input_kind,
        validation_ms=validation_ms,
        extraction_ms=(perf_counter() - extraction_started) * 1000,
    )
    result.timings.extraction_ms = (perf_counter() - extraction_started) * 1000
    result.timings.total_ms = validation_ms + result.timings.extraction_ms
    return result, gate.decision.value, []


def _scan_job_status(record: dict[str, object], user: User) -> ScanJobStatus:
    result: R3ScanResult | None = None
    scan_id = record.get("result_scan_id")
    if scan_id:
        stored = postgres_store.get_scan(str(scan_id)) if postgres_store is not None else None
        if stored is not None and stored["user_id"] == user.id:
            result = R3ScanResult.model_validate(stored["payload"])
    created_at = record["created_at"]
    started_at = record.get("started_at")
    completed_at = record.get("completed_at")
    error_code = record.get("error_code")
    error_message = record.get("error_message")
    if not isinstance(created_at, datetime):
        raise ValueError("Scan job has an invalid creation timestamp.")
    if started_at is not None and not isinstance(started_at, datetime):
        raise ValueError("Scan job has an invalid start timestamp.")
    if completed_at is not None and not isinstance(completed_at, datetime):
        raise ValueError("Scan job has an invalid completion timestamp.")
    if error_code is not None and not isinstance(error_code, str):
        raise ValueError("Scan job has an invalid error code.")
    if error_message is not None and not isinstance(error_message, str):
        raise ValueError("Scan job has an invalid error message.")
    return ScanJobStatus(
        job_id=str(record["job_id"]),
        status=str(record["status"]),
        input_kind=InputKind(str(record["input_kind"])),
        created_at=created_at,
        started_at=started_at,
        completed_at=completed_at,
        result=result,
        error_code=error_code,
        error_message=error_message,
        client_evidence_decision=(
            ClientEvidenceDecision.ACCEPTED.value
            if result is not None and result.client_evidence_provenance is not None
            else None
        ),
        server_fallback_required=(
            False if result is not None and result.client_evidence_provenance is not None else None
        ),
    )


@router.post("/jobs/product", response_model=ScanJobStatus, status_code=status.HTTP_202_ACCEPTED)
async def create_product_scan_job(
    files: Annotated[list[UploadFile], File()],
    user: Annotated[User, Depends(current_user)],
    view_types: Annotated[str, Form()] = "GENERAL",
    languages: Annotated[str, Form()] = "en",
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    evidence_json: Annotated[str | None, Form()] = None,
) -> ScanJobStatus:
    if not 1 <= len(files) <= 5:
        raise HTTPException(status_code=422, detail="A product scan supports one to five views.")
    requested = [item.strip().upper() for item in view_types.split(",") if item.strip()]
    if len(requested) == 1 and len(files) > 1:
        requested *= len(files)
    try:
        views = [ViewType(item) for item in requested]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Unsupported product view type.") from exc
    return await _create_scan_job(
        files,
        input_kind=InputKind.PRODUCT,
        view_types=views,
        languages=_languages(languages),
        user=user,
        idempotency_key=idempotency_key,
        evidence_json=evidence_json,
    )


@router.post("/jobs/{kind}", response_model=ScanJobStatus, status_code=status.HTTP_202_ACCEPTED)
async def create_single_scan_job(
    kind: str,
    file: Annotated[UploadFile, File()],
    user: Annotated[User, Depends(current_user)],
    languages: Annotated[str, Form()] = "en",
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    evidence_json: Annotated[str | None, Form()] = None,
) -> ScanJobStatus:
    try:
        input_kind = InputKind(kind.upper())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Unsupported scan job type.") from exc
    if input_kind is InputKind.PRODUCT:
        raise HTTPException(
            status_code=422, detail="Use the product job endpoint for product scans."
        )
    return await _create_scan_job(
        [file],
        input_kind=input_kind,
        view_types=[ViewType.GENERAL],
        languages=_languages(languages),
        user=user,
        idempotency_key=idempotency_key,
        evidence_json=evidence_json,
    )


@router.get("/jobs/{job_id}", response_model=ScanJobStatus)
async def get_scan_job(job_id: str, user: Annotated[User, Depends(current_user)]) -> ScanJobStatus:
    if postgres_store is None:
        raise HTTPException(status_code=404, detail="Scan job not found.")
    record = await asyncio.to_thread(postgres_store.get_scan_job, user.id, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Scan job not found.")
    return _scan_job_status(record, user)


@router.post("/client-evidence/validate", response_model=ClientEvidenceValidation)
def validate_on_device_evidence(
    evidence: ClientOcrEvidence,
    _: Annotated[User, Depends(current_user)],
) -> ClientEvidenceValidation:
    """Validate but do not trust or persist a client inference payload.

    This endpoint is intentionally quota-neutral and shadow-only. A later phase
    may bind its image digest to a durable scan job after accuracy acceptance.
    """

    return validate_client_evidence(evidence)


def _rejected_client_evidence(
    *,
    decision: ClientEvidenceDecision,
    rollout_mode: str,
    reason: str,
) -> ClientEvidenceClassification:
    capabilities = client_inference_capabilities(rollout_mode)
    logger.info(
        "client_evidence_classified",
        extra={
            "decision": decision.value,
            "rollout_mode": capabilities.android_mode.value,
            "reason_codes": [reason],
        },
    )
    return ClientEvidenceClassification(
        decision=decision.value,
        rollout_mode=capabilities.android_mode,
        accepted=False,
        reasons=[reason],
    )


@router.post("/client-evidence/classify", response_model=ClientEvidenceClassification)
async def classify_on_device_evidence(
    evidence_json: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    _: Annotated[User, Depends(current_user)],
) -> ClientEvidenceClassification:
    """Bind untrusted OCR evidence to an image and classify shadow eligibility.

    The endpoint is intentionally quota-neutral and persistence-neutral. Even
    accepted evidence cannot replace the authoritative server scan in shadow.
    """

    if len(evidence_json.encode()) > 512_000:
        await file.close()
        return _rejected_client_evidence(
            decision=ClientEvidenceDecision.INVALID,
            rollout_mode=settings.android_client_inference_mode,
            reason="EVIDENCE_PAYLOAD_TOO_LARGE",
        )
    try:
        raw_evidence = json.loads(evidence_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        await file.close()
        return _rejected_client_evidence(
            decision=ClientEvidenceDecision.INVALID,
            rollout_mode=settings.android_client_inference_mode,
            reason="EVIDENCE_JSON_INVALID",
        )
    if not isinstance(raw_evidence, dict):
        await file.close()
        return _rejected_client_evidence(
            decision=ClientEvidenceDecision.INVALID,
            rollout_mode=settings.android_client_inference_mode,
            reason="EVIDENCE_OBJECT_REQUIRED",
        )
    if raw_evidence.get("client_inference_contract_version") != "1.0.0":
        await file.close()
        return _rejected_client_evidence(
            decision=ClientEvidenceDecision.CONTRACT_UNSUPPORTED,
            rollout_mode=settings.android_client_inference_mode,
            reason="CLIENT_CONTRACT_VERSION_UNSUPPORTED",
        )
    try:
        evidence = ClientOcrEvidence.model_validate(raw_evidence)
    except (ValidationError, ValueError):
        await file.close()
        return _rejected_client_evidence(
            decision=ClientEvidenceDecision.INVALID,
            rollout_mode=settings.android_client_inference_mode,
            reason="EVIDENCE_SCHEMA_INVALID",
        )
    try:
        upload_filename = file.filename or "upload.bin"
        upload_mime_type = file.content_type or "application/octet-stream"
        content = await _read_upload(file)
        validated = validate_image_bytes(
            content,
            filename=upload_filename,
            mime_type=upload_mime_type,
            view_id="client-evidence-binding",
            view_type=ViewType.GENERAL,
            config=pipeline.config,
        )
    except ImageInputError as exc:
        return _rejected_client_evidence(
            decision=ClientEvidenceDecision.INVALID,
            rollout_mode=settings.android_client_inference_mode,
            reason=f"SOURCE_IMAGE_{exc.code}",
        )

    capabilities = client_inference_capabilities(settings.android_client_inference_mode)
    validation = validate_client_evidence(evidence)
    gate = classify_client_evidence(
        evidence,
        verified_image_sha256=validated.metadata.sha256,
        verified_image_width=validated.metadata.width,
        verified_image_height=validated.metadata.height,
        rollout_mode=capabilities.android_mode,
        policy=ClientEvidenceGatePolicy(
            min_positioned_lines=settings.android_client_min_positioned_lines,
            min_positioned_ratio=settings.android_client_min_positioned_ratio,
            min_nutrition_rows=settings.android_client_min_nutrition_rows,
            min_major_nutrients=settings.android_client_min_major_nutrients,
            min_nutrition_confidence=settings.android_client_min_nutrition_confidence,
        ),
    )
    image_binding_verified = evidence.source_image_sha256 == validated.metadata.sha256
    dimensions_binding_verified = (evidence.image_width, evidence.image_height) == (
        validated.metadata.width,
        validated.metadata.height,
    )
    logger.info(
        "client_evidence_classified",
        extra={
            "decision": gate.decision.value,
            "rollout_mode": capabilities.android_mode.value,
            "client_ocr_elapsed_ms": evidence.elapsed_ms,
            "canonical_line_count": gate.canonical_line_count,
            "positioned_line_count": gate.positioned_line_count,
            "nutrition_row_count": gate.nutrition_row_count,
            "major_nutrient_count": gate.major_nutrient_count,
            "nutrition_basis": gate.nutrition_basis,
            "reason_codes": list(gate.reasons),
        },
    )
    return ClientEvidenceClassification(
        decision=gate.decision.value,
        rollout_mode=capabilities.android_mode,
        accepted=gate.decision
        not in {
            ClientEvidenceDecision.INVALID,
            ClientEvidenceDecision.CONTRACT_UNSUPPORTED,
        },
        accepted_for="SHADOW_COMPARISON_ONLY",
        source=validation.source,
        evidence_sha256=validation.evidence_sha256,
        source_image_sha256=validation.source_image_sha256,
        canonical_line_count=validation.canonical_line_count,
        canonical_text_sha256=validation.canonical_text_sha256,
        image_binding_verified=image_binding_verified,
        dimensions_binding_verified=dimensions_binding_verified,
        eligible_for_preferred_path=gate.decision is ClientEvidenceDecision.ACCEPTED,
        nutrition_basis=gate.nutrition_basis,
        nutrition_row_count=gate.nutrition_row_count,
        major_nutrient_count=gate.major_nutrient_count,
        nutrition_confidence=gate.nutrition_confidence,
        ingredient_evidence_present=gate.ingredient_evidence_present,
        explicit_allergen_evidence_present=gate.explicit_allergen_evidence_present,
        positioned_line_count=gate.positioned_line_count,
        reasons=list(gate.reasons),
        warnings=[
            *validation.warnings,
            "The authoritative server scan remains mandatory during shadow rollout.",
        ],
    )


@router.get("/client-inference/capabilities", response_model=ClientInferenceCapabilities)
def get_client_inference_capabilities(
    user: Annotated[User, Depends(current_user)],
) -> ClientInferenceCapabilities:
    """Return the fail-safe, server-controlled Android inference rollout state."""

    capabilities = client_inference_capabilities(settings.android_client_inference_mode)
    mode = capabilities.android_mode
    if (
        mode is AndroidClientInferenceMode.PREFERRED
        and user.id not in settings.android_client_preferred_user_ids
    ):
        return client_inference_capabilities(AndroidClientInferenceMode.SHADOW.value)
    return capabilities


@router.post("/image", response_model=R3ScanResult, status_code=status.HTTP_201_CREATED)
async def scan_image(
    file: Annotated[UploadFile, File()],
    user: Annotated[User | None, Depends(optional_current_user)],
    languages: Annotated[str, Form()] = "en",
) -> R3ScanResult:
    return await _run(
        [file],
        input_kind=InputKind.IMAGE,
        view_types=[ViewType.GENERAL],
        languages=_languages(languages),
        user=user,
    )


@router.post("/product", response_model=R3ScanResult, status_code=status.HTTP_201_CREATED)
async def scan_product(
    files: Annotated[list[UploadFile], File()],
    user: Annotated[User | None, Depends(optional_current_user)],
    view_types: Annotated[str, Form()] = "GENERAL",
    languages: Annotated[str, Form()] = "en",
) -> R3ScanResult:
    if len(files) > 5:
        raise HTTPException(status_code=422, detail="A product scan supports at most five views.")
    requested = [item.strip().upper() for item in view_types.split(",") if item.strip()]
    if len(requested) == 1 and len(files) > 1:
        requested = requested * len(files)
    if len(requested) != len(files):
        raise HTTPException(status_code=422, detail="Provide one view type per uploaded image.")
    try:
        parsed = [ViewType(item) for item in requested]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Unsupported product view type.") from exc
    return await _run(
        files,
        input_kind=InputKind.PRODUCT,
        view_types=parsed,
        languages=_languages(languages),
        user=user,
    )


@router.post("/meal", response_model=R3ScanResult, status_code=status.HTTP_201_CREATED)
async def scan_meal(
    file: Annotated[UploadFile, File()],
    user: Annotated[User | None, Depends(optional_current_user)],
) -> R3ScanResult:
    return await _run(
        [file],
        input_kind=InputKind.MEAL,
        view_types=[ViewType.GENERAL],
        languages=["en"],
        user=user,
    )


@router.post("/barcode", response_model=R3ScanResult, status_code=status.HTTP_201_CREATED)
async def scan_barcode(
    file: Annotated[UploadFile, File()],
    user: Annotated[User | None, Depends(optional_current_user)],
) -> R3ScanResult:
    return await _run(
        [file],
        input_kind=InputKind.BARCODE,
        view_types=[ViewType.GENERAL],
        languages=["en"],
        user=user,
    )


@router.post("/ocr", response_model=R3ScanResult, status_code=status.HTTP_201_CREATED)
async def scan_ocr(
    file: Annotated[UploadFile, File()],
    user: Annotated[User | None, Depends(optional_current_user)],
    languages: Annotated[str, Form()] = "en",
) -> R3ScanResult:
    return await _run(
        [file],
        input_kind=InputKind.OCR,
        view_types=[ViewType.GENERAL],
        languages=_languages(languages),
        user=user,
    )


@router.get("/history", response_model=list[ScanHistoryItem])
def scan_history(
    user: Annotated[User, Depends(current_user)],
    limit: int = Query(default=25, ge=1, le=100),
) -> list[ScanHistoryItem]:
    if postgres_store is not None:
        results = [
            R3ScanResult.model_validate(payload) for payload in postgres_store.list_scans(user.id)
        ]
    else:
        results = scan_store.list(owner_id=user.id)
    return [_history_item(result) for result in results[:limit]]


@router.get("/{scan_id}", response_model=R3ScanResult)
def get_scan(
    scan_id: str, user: Annotated[User | None, Depends(optional_current_user)]
) -> R3ScanResult:
    try:
        return get_owned_scan_result(scan_id, user)
    except ScanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Scan not found or already deleted.") from exc


@router.patch("/{scan_id}/corrections", response_model=R3ScanResult)
def correct_scan(
    scan_id: str,
    request: CorrectionRequest,
    user: Annotated[User | None, Depends(optional_current_user)],
) -> R3ScanResult:
    try:
        current = get_owned_scan_result(scan_id, user)
        correction_store = EphemeralScanStore()
        correction_store.save(current)
        updated = correction_store.correct(scan_id, request)
        if postgres_store is not None and user is not None:
            postgres_store.put_scan(user.id, scan_id, updated.model_dump(mode="json"))
        else:
            scan_store.save(updated, owner_id=user.id if user is not None else None)
        return updated
    except ScanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Scan not found or already deleted.") from exc


@router.delete("/{scan_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_scan(
    scan_id: str, user: Annotated[User | None, Depends(optional_current_user)]
) -> Response:
    if postgres_store is not None and user is not None:
        deleted = postgres_store.delete_scan(user.id, scan_id)
    else:
        _authorize_scan(scan_id, user)
        deleted = scan_store.delete(scan_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Scan not found or already deleted.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _languages(raw: str) -> list[str]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return values[:4] or ["en"]


def _reserve_scan(user: User | None) -> None:
    if user is None:
        return
    allowance = int(
        resolve_entitlements(user.plan, user.subscription_status, set(user.roles)).values[
            "scan.monthly_limit"
        ]
    )
    now = datetime.now(UTC)
    period_start = date(now.year, now.month, 1)
    if postgres_store is not None:
        count = postgres_store.increment_scan_usage(user.id, period_start, allowance)
    else:
        key = (user.id, period_start)
        with _scan_usage_lock:
            stale = [candidate for candidate in _scan_usage if candidate[1] != period_start]
            for candidate in stale:
                _scan_usage.pop(candidate, None)
            used = _scan_usage.get(key, 0)
            count = None if used >= allowance else used + 1
            if count is not None:
                _scan_usage[key] = count
    if count is None:
        raise HTTPException(status_code=429, detail="Monthly scan allowance reached.")


def _release_scan_reservation(user: User | None) -> None:
    if user is None:
        return
    now = datetime.now(UTC)
    period_start = date(now.year, now.month, 1)
    if postgres_store is not None:
        postgres_store.decrement_scan_usage(user.id, period_start)
        return
    key = (user.id, period_start)
    with _scan_usage_lock:
        current = _scan_usage.get(key, 0)
        if current <= 1:
            _scan_usage.pop(key, None)
        else:
            _scan_usage[key] = current - 1


def _authorize_scan(scan_id: str, user: User | None) -> None:
    if user is None:
        return
    try:
        owner_id = scan_store.owner_of(scan_id)
    except ScanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Scan not found or already deleted.") from exc
    if owner_id != user.id:
        raise HTTPException(status_code=404, detail="Scan not found or already deleted.")


def get_scan_result(scan_id: str) -> R3ScanResult:
    if postgres_store is not None:
        row = postgres_store.get_scan(scan_id)
        if row is None:
            raise ScanNotFoundError(scan_id)
        return R3ScanResult.model_validate(row["payload"])
    return scan_store.get(scan_id)


def get_owned_scan_result(scan_id: str, user: User | None) -> R3ScanResult:
    if postgres_store is not None and user is not None:
        row = postgres_store.get_scan(scan_id)
        if row is None or row["user_id"] != user.id:
            raise ScanNotFoundError(scan_id)
        return R3ScanResult.model_validate(row["payload"])
    _authorize_scan(scan_id, user)
    return scan_store.get(scan_id)


def _history_item(result: R3ScanResult) -> ScanHistoryItem:
    return ScanHistoryItem(
        scan_id=result.scan_id,
        created_at=result.created_at,
        input_kind=result.input_kind,
        status=result.status,
        product_name=(
            result.product_name_candidates[0].value if result.product_name_candidates else None
        ),
        brand=result.brand_candidates[0].value if result.brand_candidates else None,
        confidence=result.confidence_summary.numeric_score,
    )
