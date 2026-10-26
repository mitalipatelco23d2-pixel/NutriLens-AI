"""Strict, untrusted client-inference evidence boundary.

Client OCR can reduce paid inference, but it is never trusted merely because an
authenticated app sent it. This module allowlists runtimes, bounds payload size,
validates coordinates against the declared image, and produces a canonical
digest for later shadow comparison or image binding.
"""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ClientContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ClientInferenceSource(StrEnum):
    ANDROID_MLKIT = "CLIENT_ANDROID_MLKIT"
    ANDROID_YOLO_ONNX = "CLIENT_ANDROID_YOLO_ONNX"
    WEB_ONNX_WEBGPU = "CLIENT_WEB_ONNX_WEBGPU"
    WEB_ONNX_WASM = "CLIENT_WEB_ONNX_WASM"


class AndroidClientInferenceMode(StrEnum):
    DISABLED = "disabled"
    SHADOW = "shadow"
    PREFERRED = "preferred"


CLIENT_INFERENCE_CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"
ANDROID_MLKIT_OCR_PROVIDER: Literal["ML_KIT_TEXT_RECOGNITION_V2"] = "ML_KIT_TEXT_RECOGNITION_V2"
ANDROID_MLKIT_OCR_PROVIDER_VERSION: Literal["16.0.1"] = "16.0.1"


def _android_platforms() -> list[Literal["ANDROID"]]:
    return ["ANDROID"]


def _android_ocr_providers() -> list[Literal["ML_KIT_TEXT_RECOGNITION_V2"]]:
    return [ANDROID_MLKIT_OCR_PROVIDER]


def _android_ocr_provider_versions() -> list[Literal["16.0.1"]]:
    return [ANDROID_MLKIT_OCR_PROVIDER_VERSION]


class ClientInferenceCapabilities(ClientContractModel):
    client_inference_contract_version: Literal["1.0.0"] = CLIENT_INFERENCE_CONTRACT_VERSION
    android_mode: AndroidClientInferenceMode
    accepted_platforms: list[Literal["ANDROID"]] = Field(default_factory=_android_platforms)
    accepted_ocr_providers: list[Literal["ML_KIT_TEXT_RECOGNITION_V2"]] = Field(
        default_factory=_android_ocr_providers
    )
    accepted_ocr_provider_versions: list[Literal["16.0.1"]] = Field(
        default_factory=_android_ocr_provider_versions
    )
    evidence_use: Literal["SHADOW_COMPARISON_ONLY", "SERVER_PARSED_CLIENT_EVIDENCE"] = (
        "SHADOW_COMPARISON_ONLY"
    )
    server_result_authoritative: Literal[True] = True
    server_fallback_required: bool = True
    rejected_evidence_requires_server_fallback: Literal[True] = True
    configuration_warning: str | None = None


def client_inference_capabilities(configured_mode: str) -> ClientInferenceCapabilities:
    try:
        mode = AndroidClientInferenceMode(configured_mode.strip().lower())
        warning = None
    except ValueError:
        mode = AndroidClientInferenceMode.DISABLED
        warning = "Invalid server rollout mode; client inference was disabled safely."
    return ClientInferenceCapabilities(
        android_mode=mode,
        configuration_warning=warning,
        evidence_use=(
            "SERVER_PARSED_CLIENT_EVIDENCE"
            if mode is AndroidClientInferenceMode.PREFERRED
            else "SHADOW_COMPARISON_ONLY"
        ),
        server_fallback_required=mode is not AndroidClientInferenceMode.PREFERRED,
    )


class ClientPixelBounds(ClientContractModel):
    left: int = Field(ge=0, le=8192)
    top: int = Field(ge=0, le=8192)
    right: int = Field(gt=0, le=8192)
    bottom: int = Field(gt=0, le=8192)

    @model_validator(mode="after")
    def ordered(self) -> ClientPixelBounds:
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError("Client evidence bounds must have positive area.")
        return self


class ClientOcrLine(ClientContractModel):
    text: str = Field(min_length=1, max_length=2_000)
    bounds: ClientPixelBounds | None = None
    recognized_languages: list[str] = Field(default_factory=list, max_length=4)
    confidence: float | None = Field(default=None, ge=0, le=1)


class ClientOcrBlock(ClientContractModel):
    text: str = Field(min_length=1, max_length=20_000)
    bounds: ClientPixelBounds | None = None
    recognized_languages: list[str] = Field(default_factory=list, max_length=4)
    lines: list[ClientOcrLine] = Field(default_factory=list, max_length=128)


class ClientOcrEvidence(ClientContractModel):
    client_inference_contract_version: Literal["1.0.0"]
    platform: Literal["ANDROID"]
    app_version: str = Field(min_length=1, max_length=64)
    source: Literal[ClientInferenceSource.ANDROID_MLKIT]
    ocr_provider: Literal["ML_KIT_TEXT_RECOGNITION_V2"]
    ocr_provider_version: Literal["16.0.1"]
    detector_provider: None = None
    detector_provider_version: None = None
    cold_start: bool = False
    elapsed_ms: int = Field(ge=0, le=300_000)
    image_width: int = Field(gt=0, le=8192)
    image_height: int = Field(gt=0, le=8192)
    source_image_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    orientation_degrees: Literal[0, 90, 180, 270]
    text: str = Field(default="", max_length=200_000)
    blocks: list[ClientOcrBlock] = Field(default_factory=list, max_length=256)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_untrusted_evidence(self) -> ClientOcrEvidence:
        if self.image_width * self.image_height > 40_000_000:
            raise ValueError("Client image dimensions exceed the validation limit.")
        lines = [line for block in self.blocks for line in block.lines]
        if len(lines) > 2_000:
            raise ValueError("Client OCR evidence has too many lines.")
        if sum(len(line.text) for line in lines) > 120_000:
            raise ValueError("Client OCR evidence text exceeds the validation limit.")
        if sum(len(block.text) for block in self.blocks) > 200_000:
            raise ValueError("Client OCR block text exceeds the validation limit.")
        languages = [language for block in self.blocks for language in block.recognized_languages]
        languages.extend(
            language
            for block in self.blocks
            for line in block.lines
            for language in line.recognized_languages
        )
        if any(
            len(language) > 12 or not language.replace("-", "").isalnum() for language in languages
        ):
            raise ValueError("Client OCR language tags are invalid.")
        for bounds in [
            *(block.bounds for block in self.blocks),
            *(line.bounds for line in lines),
        ]:
            if bounds is not None and (
                bounds.right > self.image_width or bounds.bottom > self.image_height
            ):
                raise ValueError("Client OCR bounds exceed the declared image dimensions.")

        if self.confidence is not None or any(line.confidence is not None for line in lines):
            raise ValueError("ML Kit OCR confidence must remain unavailable.")
        return self

    def canonical_lines(self) -> list[str]:
        return [line.text for block in self.blocks for line in block.lines]


class ClientEvidenceValidation(ClientContractModel):
    accepted: Literal[True] = True
    accepted_for: Literal["SHADOW_COMPARISON_ONLY"] = "SHADOW_COMPARISON_ONLY"
    source: ClientInferenceSource
    evidence_sha256: str
    source_image_sha256: str
    canonical_line_count: int
    canonical_text_sha256: str
    warnings: list[str] = Field(default_factory=list)


class ClientEvidenceClassification(ClientContractModel):
    decision: Literal[
        "CLIENT_EVIDENCE_ACCEPTED",
        "SERVER_FALLBACK_REQUIRED",
        "CLIENT_EVIDENCE_INVALID",
        "CLIENT_CONTRACT_UNSUPPORTED",
    ]
    rollout_mode: AndroidClientInferenceMode
    accepted: bool
    accepted_for: Literal["SHADOW_COMPARISON_ONLY"] | None = None
    source: ClientInferenceSource | None = None
    evidence_sha256: str | None = None
    source_image_sha256: str | None = None
    canonical_line_count: int = Field(default=0, ge=0)
    canonical_text_sha256: str | None = None
    image_binding_verified: bool = False
    dimensions_binding_verified: bool = False
    eligible_for_preferred_path: bool = False
    server_result_authoritative: Literal[True] = True
    server_fallback_required: Literal[True] = True
    nutrition_basis: str = "UNKNOWN"
    nutrition_row_count: int = Field(default=0, ge=0)
    major_nutrient_count: int = Field(default=0, ge=0)
    nutrition_confidence: float | None = Field(default=None, ge=0, le=1)
    ingredient_evidence_present: bool = False
    explicit_allergen_evidence_present: bool = False
    positioned_line_count: int = Field(default=0, ge=0)
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def validate_client_evidence(evidence: ClientOcrEvidence) -> ClientEvidenceValidation:
    canonical_payload = json.dumps(
        evidence.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    canonical_text = "\n".join(evidence.canonical_lines()).encode()
    warnings = [
        "Client evidence is untrusted and is not authoritative during shadow validation.",
    ]
    if not evidence.canonical_lines():
        warnings.append("No canonical OCR lines were supplied.")
    return ClientEvidenceValidation(
        source=evidence.source,
        evidence_sha256=sha256(canonical_payload).hexdigest(),
        source_image_sha256=evidence.source_image_sha256,
        canonical_line_count=len(evidence.canonical_lines()),
        canonical_text_sha256=sha256(canonical_text).hexdigest(),
        warnings=warnings,
    )
