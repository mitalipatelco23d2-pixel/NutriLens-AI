import hashlib
import io
import json

from fastapi.testclient import TestClient
from PIL import Image

from backend.auth import create_session_token, user_store
from backend.main import app


def _headers() -> dict[str, str]:
    user = user_store.upsert_google_user(
        {
            "sub": "client-evidence-owner",
            "email": "client-evidence@example.com",
            "email_verified": True,
        }
    )
    token, _ = create_session_token(user)
    return {"Authorization": f"Bearer {token}"}


def _payload() -> dict[str, object]:
    return {
        "client_inference_contract_version": "1.0.0",
        "platform": "ANDROID",
        "app_version": "1.0.0+1",
        "source": "CLIENT_ANDROID_MLKIT",
        "ocr_provider": "ML_KIT_TEXT_RECOGNITION_V2",
        "ocr_provider_version": "16.0.1",
        "detector_provider": None,
        "detector_provider_version": None,
        "cold_start": False,
        "elapsed_ms": 245,
        "image_width": 1080,
        "image_height": 1920,
        "source_image_sha256": "a" * 64,
        "orientation_degrees": 0,
        "text": "This top-level text is not trusted as canonical.",
        "confidence": None,
        "blocks": [
            {
                "text": "Ingredients: Milk",
                "bounds": {"left": 10, "top": 20, "right": 500, "bottom": 100},
                "recognized_languages": ["en"],
                "lines": [
                    {
                        "text": "Ingredients: Milk",
                        "bounds": {"left": 10, "top": 20, "right": 500, "bottom": 100},
                        "recognized_languages": ["en"],
                        "confidence": None,
                    }
                ],
            }
        ],
    }


def _png_fixture() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (800, 1200), color="white").save(output, format="PNG")
    return output.getvalue()


def _bound_structured_payload(image: bytes) -> dict[str, object]:
    lines = [
        "Nutrition Facts",
        "Per 100 ml",
        "Energy 50 kcal",
        "Protein 3.6 g",
        "Carbohydrate 5.5 g",
        "Total Sugar 5.5 g",
        "Total Fat 1.5 g",
        "Sodium 45 mg",
        "Ingredients: Pasteurized Cow Milk",
        "Contains: Milk",
    ]
    payload = _payload()
    payload.update(
        {
            "image_width": 800,
            "image_height": 1200,
            "source_image_sha256": hashlib.sha256(image).hexdigest(),
            "text": "\n".join(lines),
            "blocks": [
                {
                    "text": "\n".join(lines),
                    "bounds": {"left": 20, "top": 20, "right": 760, "bottom": 700},
                    "recognized_languages": ["en"],
                    "lines": [
                        {
                            "text": line,
                            "bounds": {
                                "left": 40,
                                "top": 40 + index * 55,
                                "right": 700,
                                "bottom": 80 + index * 55,
                            },
                            "recognized_languages": ["en"],
                            "confidence": None,
                        }
                        for index, line in enumerate(lines)
                    ],
                }
            ],
        }
    )
    return payload


def test_client_evidence_requires_owner_authentication() -> None:
    response = TestClient(app).post("/api/v1/scan/client-evidence/validate", json=_payload())
    assert response.status_code == 401


def test_client_evidence_is_bounded_and_accepted_for_shadow_only() -> None:
    response = TestClient(app).post(
        "/api/v1/scan/client-evidence/validate", headers=_headers(), json=_payload()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted_for"] == "SHADOW_COMPARISON_ONLY"
    assert body["canonical_line_count"] == 1
    assert body["source_image_sha256"] == "a" * 64
    assert len(body["evidence_sha256"]) == 64
    assert "top-level text" not in str(body)


def test_client_evidence_rejects_impossible_bounds_and_fake_mlkit_confidence() -> None:
    payload = _payload()
    payload["blocks"][0]["lines"][0]["bounds"]["right"] = 2000  # type: ignore[index]
    payload["blocks"][0]["lines"][0]["confidence"] = 0.99  # type: ignore[index]
    response = TestClient(app).post(
        "/api/v1/scan/client-evidence/validate", headers=_headers(), json=payload
    )
    assert response.status_code == 422


def test_client_evidence_rejects_unapproved_runtime() -> None:
    payload = _payload()
    payload["source"] = "CLIENT_TAMPERED_RUNTIME"
    response = TestClient(app).post(
        "/api/v1/scan/client-evidence/validate", headers=_headers(), json=payload
    )
    assert response.status_code == 422


def test_client_evidence_rejects_obsolete_contract_and_spoofed_owner() -> None:
    payload = _payload()
    payload["client_inference_contract_version"] = "0.9.0"
    payload["user_id"] = "another-user"
    response = TestClient(app).post(
        "/api/v1/scan/client-evidence/validate", headers=_headers(), json=payload
    )
    assert response.status_code == 422


def test_client_inference_capability_is_authenticated_and_shadow_by_default() -> None:
    client = TestClient(app)
    assert client.get("/api/v1/scan/client-inference/capabilities").status_code == 401
    response = client.get("/api/v1/scan/client-inference/capabilities", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["client_inference_contract_version"] == "1.0.0"
    assert body["android_mode"] == "shadow"
    assert body["evidence_use"] == "SHADOW_COMPARISON_ONLY"
    assert body["server_result_authoritative"] is True
    assert body["server_fallback_required"] is True


def test_bound_structured_evidence_is_eligible_but_server_remains_authoritative() -> None:
    image = _png_fixture()
    response = TestClient(app).post(
        "/api/v1/scan/client-evidence/classify",
        headers=_headers(),
        data={"evidence_json": json.dumps(_bound_structured_payload(image))},
        files={"file": ("fixture.png", image, "image/png")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "CLIENT_EVIDENCE_ACCEPTED"
    assert body["accepted_for"] == "SHADOW_COMPARISON_ONLY"
    assert body["image_binding_verified"] is True
    assert body["dimensions_binding_verified"] is True
    assert body["eligible_for_preferred_path"] is True
    assert body["server_result_authoritative"] is True
    assert body["server_fallback_required"] is True
    assert body["nutrition_basis"] == "PER_100_ML"
    assert body["nutrition_row_count"] >= 4
    assert body["major_nutrient_count"] >= 3
    assert body["explicit_allergen_evidence_present"] is True


def test_bound_evidence_rejects_image_digest_mismatch() -> None:
    image = _png_fixture()
    payload = _bound_structured_payload(image)
    payload["source_image_sha256"] = "f" * 64
    response = TestClient(app).post(
        "/api/v1/scan/client-evidence/classify",
        headers=_headers(),
        data={"evidence_json": json.dumps(payload)},
        files={"file": ("fixture.png", image, "image/png")},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["decision"] == "CLIENT_EVIDENCE_INVALID"
    assert body["eligible_for_preferred_path"] is False
    assert body["server_fallback_required"] is True
    assert body["reasons"] == ["SOURCE_IMAGE_SHA256_MISMATCH"]


def test_bound_sparse_evidence_requires_server_fallback() -> None:
    image = _png_fixture()
    payload = _bound_structured_payload(image)
    payload["blocks"] = _payload()["blocks"]
    response = TestClient(app).post(
        "/api/v1/scan/client-evidence/classify",
        headers=_headers(),
        data={"evidence_json": json.dumps(payload)},
        files={"file": ("fixture.png", image, "image/png")},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["decision"] == "SERVER_FALLBACK_REQUIRED"
    assert body["eligible_for_preferred_path"] is False
    assert "INSUFFICIENT_OCR_LINES" in body["reasons"]


def test_classification_reports_unsupported_contract_without_processing_image() -> None:
    image = _png_fixture()
    payload = _bound_structured_payload(image)
    payload["client_inference_contract_version"] = "0.9.0"
    response = TestClient(app).post(
        "/api/v1/scan/client-evidence/classify",
        headers=_headers(),
        data={"evidence_json": json.dumps(payload)},
        files={"file": ("fixture.png", image, "image/png")},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["decision"] == "CLIENT_CONTRACT_UNSUPPORTED"
    assert body["accepted"] is False
    assert body["server_fallback_required"] is True


def test_classification_requires_authentication() -> None:
    image = _png_fixture()
    response = TestClient(app).post(
        "/api/v1/scan/client-evidence/classify",
        data={"evidence_json": json.dumps(_bound_structured_payload(image))},
        files={"file": ("fixture.png", image, "image/png")},
    )
    assert response.status_code == 401
