from __future__ import annotations

import csv
import hashlib
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.api import routes
from backend.app.knowledge_base.service import REQUIRED_COLUMNS, KnowledgeBaseService
from backend.app.main import create_app
from backend.app.ocr.extractor import OcrResult
from backend.app.ocr.preprocessing import PreparedImage
from backend.app.ocr.service import OcrExecution
from backend.app.services import team_pipeline as team_pipeline_module
from backend.app.services.m5 import M5Phase1Explainer
from backend.app.services.recommendations import generate_recommendations
from backend.app.services.team_pipeline import TeamAnalysisPipeline


def kb_row(ingredient: str, aliases: str = "", source: str = "WHO") -> dict[str, str]:
    return {
        "ingredient": ingredient,
        "aliases": aliases,
        "category": "Test category",
        "concern_level": "Moderate",
        "concern_type": "Dataset classification",
        "reason": "Teammate-provided dataset reason.",
        "possible_effect": "Unverified effect text.",
        "usage": "Food-label use.",
        "avoid_for": "Unverified audience text.",
        "source": source,
        "product_count": "10",
        "long_term_risk": "Unverified long-term text.",
    }


def write_kb(path: Path, rows: list[dict[str, str]]) -> str:
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_kb(tmp_path: Path) -> KnowledgeBaseService:
    path = tmp_path / "kb.csv"
    digest = write_kb(
        path,
        [
            kb_row("wheat flour", "flour; wheat flour", "FDA"),
            kb_row("monosodium glutamate", "MSG; E621", "FDA"),
            kb_row("palm oil", "palm fat", "WHO"),
        ],
    )
    return KnowledgeBaseService(path, expected_sha256=digest)


def nlp_result(*, basis: str = "per_100g") -> dict:
    return {
        "basis": basis,
        "ingredients": ["Wheat flour", "MSG", "Oats"],
        "nutrition": {
            "sugars_100g": 25.0,
            "saturated_fat_100g": 6.0,
            "trans_fat_100g": 0.0,
            "sodium_100g": 0.4,
        },
        "allergens": ["Milk"],
        "additives": ["INS 621"],
        "warnings": [],
        "integration": {"status": "available", "provider": "test_m1"},
    }


def m2_result(*, basis: str = "per_100g", complete: bool = True) -> dict:
    nutrition_available = complete and basis == "per_100g"
    return {
        "status": "available" if nutrition_available else "partial",
        "health_score": 72.0 if nutrition_available else None,
        "score_level": "GOOD" if nutrition_available else None,
        "risk_level": "MODERATE",
        "basis": basis,
        "nutrition_score": {
            "available": nutrition_available,
            "basis": basis,
            "health_score": 72.0 if nutrition_available else None,
            "score_level": "GOOD" if nutrition_available else None,
            "reasons": ["High sugar content"] if nutrition_available else [],
            "breakdown": {"nutrition_penalty": 26.0} if nutrition_available else {},
            "nutrition_breakdown": {"sugar_penalty": 12.0}
            if nutrition_available
            else {},
            "warnings": [],
            "missing_nutrients": [] if complete else ["trans_fat_100g"],
            "detail": None
            if nutrition_available
            else "Required nutrition measurements are missing or use an unsupported basis.",
            "model_version": "m2_nutrition_rules_v1",
        },
        "ingredient_risk": {
            "available": True,
            "risk_level": "MODERATE",
            "probabilities": {"LOW": 20.0, "MODERATE": 70.0, "HIGH": 10.0},
            "ingredient_text": "wheat flour, msg, oats",
            "model_version": "m2_ingredient_risk_v1",
        },
        "model_version": "m2_combined_v1",
        "warnings": [],
    }


def test_kb_supports_exact_alias_and_e_number_without_claiming_citations(tmp_path):
    result = make_kb(tmp_path).lookup(
        ["WHEAT-FLOUR", "msg", "INS 621", "oil"]
    )

    assert result["status"] == "available"
    assert [item["matched_by"] for item in result["matched"]] == [
        "exact",
        "alias",
        "e_number",
    ]
    assert result["unmatched"] == [
        {"input_ingredient": "oil", "normalized": "oil", "reason": "not_found"}
    ]
    assert result["matched"][0]["dataset_source_label"] == "FDA"
    assert result["matched"][0]["citation_verified"] is False
    assert "long_term_risk" not in result["matched"][0]
    assert result["dataset"]["hash_matches_reviewed_file"] is True
    assert result["dataset"]["trust"] == "unverified_teammate_provided_dataset"


def test_kb_does_not_use_permissive_substring_matching(tmp_path):
    result = make_kb(tmp_path).lookup(["oil", "salty", "palm"])

    assert result["matched"] == []
    assert [item["reason"] for item in result["unmatched"]] == [
        "not_found",
        "not_found",
        "not_found",
    ]


def test_kb_refuses_ambiguous_aliases(tmp_path):
    path = tmp_path / "ambiguous.csv"
    digest = write_kb(
        path,
        [kb_row("wheat flour", "flour"), kb_row("corn flour", "flour")],
    )
    result = KnowledgeBaseService(path, expected_sha256=digest).lookup(["flour"])

    assert result["matched"] == []
    assert result["unmatched"][0]["reason"] == "ambiguous_alias"


def test_missing_kb_is_an_explicit_optional_failure(tmp_path):
    service = KnowledgeBaseService(
        tmp_path / "missing.csv", expected_sha256="0" * 64
    )
    result = service.lookup(["sugar"])

    assert result["status"] == "unavailable"
    assert result["unmatched"][0]["reason"] == "dataset_unavailable"
    assert "unavailable" in result["warnings"][0]


def test_malformed_kb_schema_is_rejected(tmp_path):
    path = tmp_path / "malformed.csv"
    path.write_text("ingredient,source\nsugar,WHO\n", encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = KnowledgeBaseService(path, expected_sha256=digest).lookup(["sugar"])

    assert result["status"] == "unavailable"
    assert "schema is invalid" in result["warnings"][0]


def test_changed_kb_hash_is_rejected_and_recorded(tmp_path):
    path = tmp_path / "changed.csv"
    write_kb(path, [kb_row("sugar")])
    result = KnowledgeBaseService(path, expected_sha256="0" * 64).lookup(["sugar"])

    assert result["status"] == "unavailable"
    assert result["dataset"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result["dataset"]["hash_matches_reviewed_file"] is False


@pytest.mark.parametrize(
    ("basis", "thresholds_applied"),
    [
        ("per_100g", True),
        ("per_100ml", False),
        ("per_serving", False),
        ("unknown", False),
    ],
)
def test_recommendations_respect_nutrition_basis(basis, thresholds_applied):
    result = generate_recommendations(
        nlp_result(basis=basis), m2_result(basis=basis)
    )

    assert result["basis"] == basis
    assert result["nutrition_thresholds_applied"] is thresholds_applied
    nutrition_categories = {"sugar", "saturated_fat", "trans_fat", "sodium"}
    present = {item["category"] for item in result["items"]}
    if thresholds_applied:
        assert {"sugar", "saturated_fat", "sodium"} <= present
    else:
        assert not nutrition_categories.intersection(present)
        assert any("no conversion" in detail for detail in result["omissions"])


def test_missing_m2_nutrition_omits_all_threshold_recommendations():
    result = generate_recommendations(
        nlp_result(), m2_result(complete=False)
    )

    assert result["nutrition_thresholds_applied"] is False
    assert not {"sugar", "saturated_fat", "trans_fat", "sodium"}.intersection(
        item["category"] for item in result["items"]
    )
    assert "trans_fat_100g" in result["omissions"][0]


def test_m5_preserves_actual_m2_result_and_keeps_evidence_separate(tmp_path):
    source = m2_result()
    before = deepcopy(source)
    result = M5Phase1Explainer(make_kb(tmp_path)).explain(nlp_result(), source)

    assert source == before
    assert result["nutrition"]["health_score"] == source["health_score"]
    assert result["nutrition"]["reasons"] == ["High sugar content"]
    assert result["ingredient_risk"]["probabilities"] == source["ingredient_risk"][
        "probabilities"
    ]
    assert result["ingredient_risk"]["model_rerun"] is False
    assert result["ingredient_risk"]["attribution_performed"] is False
    assert result["ingredient_risk"]["knowledge_base_causality_claimed"] is False
    assert result["methodology"]["knowledge_base"] == "deterministic_lookup_not_rag"


def test_partial_m2_and_missing_kb_produce_partial_m5_result(tmp_path):
    missing_kb = KnowledgeBaseService(
        tmp_path / "missing.csv", expected_sha256="0" * 64
    )
    result = M5Phase1Explainer(missing_kb).explain(
        nlp_result(), m2_result(complete=False)
    )

    assert result["status"] == "partial"
    assert result["knowledge_base"]["status"] == "unavailable"
    assert result["nutrition"]["available"] is False
    assert result["ingredient_risk"]["available"] is True


def test_pipeline_calls_m2_once_and_m5_does_not_rerun_risk_model(tmp_path):
    expected = m2_result()

    class CountingM2:
        provider = "counting_m2"

        def __init__(self):
            self.calls = 0

        def predict(self, parsed):
            self.calls += 1
            if self.calls > 1:
                raise AssertionError("M5 must not invoke M2 or its risk model again.")
            return deepcopy(expected)

    predictor = CountingM2()
    response = TeamAnalysisPipeline(
        health_predictor=predictor,
        explainer=M5Phase1Explainer(make_kb(tmp_path)),
    ).analyze_text(
        {
            "raw_text": (
                "Nutrition Information per 100 g\nSugars 25 g\n"
                "Saturated Fat 6 g\nTrans Fat 0 g\nSodium 400 mg\n"
                "Ingredients: Wheat flour, MSG, Oats\nContains: Milk"
            )
        }
    )

    assert predictor.calls == 1
    assert response.health == expected
    assert response.explanation["ingredient_risk"]["model_rerun"] is False
    assert response.status == "success"


def test_kb_unavailability_preserves_pipeline_partial_success(tmp_path):
    class M2:
        provider = "test_m2"

        def predict(self, parsed):
            return m2_result()

    response = TeamAnalysisPipeline(
        health_predictor=M2(),
        explainer=M5Phase1Explainer(
            KnowledgeBaseService(
                tmp_path / "missing.csv", expected_sha256="0" * 64
            )
        ),
    ).analyze_text({"raw_text": "Ingredients: Wheat flour"})

    assert response.status == "partial_success"
    assert response.health["health_score"] == 72.0
    assert response.explanation["knowledge_base"]["status"] == "unavailable"


def test_stable_analyze_api_returns_m5_in_existing_explanation_field(
    tmp_path, monkeypatch
):
    class M2:
        provider = "test_m2"

        def predict(self, parsed):
            return m2_result()

    label = """Nutrition Information per 100 g
Sugars 25 g
Saturated Fat 6 g
Trans Fat 0 g
Sodium 400 mg
Ingredients: Wheat flour, MSG, Oats
Contains: Milk"""
    execution = OcrExecution(
        OcrResult(label, "tesseract", "eng", 92.0),
        PreparedImage(Image.new("L", (600, 900)), 600, 900, True),
    )
    pipeline = TeamAnalysisPipeline(
        health_predictor=M2(),
        explainer=M5Phase1Explainer(make_kb(tmp_path)),
    )
    monkeypatch.setattr(
        team_pipeline_module, "execute_ocr", lambda *args, **kwargs: execution
    )
    monkeypatch.setattr(routes, "get_team_analysis_pipeline", lambda: pipeline)

    response = TestClient(create_app()).post(
        "/api/v1/analyze",
        files={"image": ("synthetic.png", b"synthetic-image", "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "request_id",
        "status",
        "ocr",
        "analysis",
        "health",
        "explanation",
        "integrations",
        "warnings",
    }
    assert payload["status"] == "success"
    assert payload["health"] == m2_result()
    assert payload["explanation"]["knowledge_base"]["status"] == "available"
    assert payload["explanation"]["methodology"]["dynamic_shap"] == "not_implemented"
    assert payload["integrations"]["explanation"] == {
        "status": "available",
        "provider": "member_5_phase_1_deterministic",
    }
