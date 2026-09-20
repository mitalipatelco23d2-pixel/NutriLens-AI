from backend.app.services.team_contracts import (
    analyze_label_text,
    explain_analysis,
    parse_ocr_nutrition,
    predict_health,
)
from backend.app.nlp.parser import extract_explicit_allergens
from backend.app.ocr.extractor import OcrEvidence, OcrResult
from backend.app.services.team_pipeline import TeamAnalysisPipeline


LABEL = """Value Per 100 g
Energy 100 kcal
Fat 1 g
Saturated Fat 0 g
Sugars 2 g
Fiber 3 g
Protein 4 g
Salt 0.5 g
Sodium 100 mg
Ingredients: oats, sugar"""


class Member1:
    provider = "member_1_test"

    def analyze(self, ocr_result):
        return {"ingredients": ["normalized oats"], "nutrition": {}, "warnings": []}


class Member2:
    provider = "member_2_test"

    def predict(self, nlp_result):
        return {"health_score": 68, "risk_level": "moderate", "model_version": "test"}


class Member5:
    provider = "member_5_test"

    def explain(self, nlp_result, health_result):
        return {"summary": "configured explanation", "sources": []}


class BrokenAdapter:
    provider = "broken_test"

    def analyze(self, ocr_result): raise RuntimeError("failed")
    def predict(self, nlp_result): raise RuntimeError("failed")
    def explain(self, nlp_result, health_result): raise RuntimeError("failed")


class LegacyScorer:
    def predict(self, features):
        assert features["energy_100g"] == 418.4
        return 6.5


def test_member1_nlp_uses_existing_backend_nutrition_parser():
    result = analyze_label_text({"raw_text": LABEL})
    assert result["ingredients"] == ["oats", "sugar"]
    assert result["nutrition"]["energy_kcal_100g"] == 100
    assert result["nutrition"]["energy_kj_100g"] == 418.4
    assert result["integration"] == {
        "status": "available",
        "provider": "member_1_packaged_food_nlp",
    }


def test_table_basis_is_shared_only_across_detected_nutrition_table_passes():
    ocr_result = OcrResult(
        text="blurred package text",
        engine="tesseract",
        language="eng",
        mean_confidence=44.0,
        candidate_evidence=(
            OcrEvidence(
                "Amount per 100 g\nEnergy 313 kcal",
                (),
                "nutrition_table",
            ),
            OcrEvidence(
                "Total Fat <0.5 g\nProtein 22 g",
                (),
                "nutrition_table",
            ),
        ),
    )

    result = parse_ocr_nutrition(ocr_result)

    assert result.basis == "per_100g"
    assert result.nutrients["fat_100g"].qualifier == "less_than"
    assert result.nutrients["proteins_100g"].value == 22
    assert result.nutrients["energy_100g"].source_value == 313


def test_fallback_allergen_extraction_requires_explicit_label_text():
    assert extract_explicit_allergens("Allergen: CONTAINS MILK") == ["Milk"]
    assert extract_explicit_allergens("Ingredients: pasteurized cow milk") == []


def test_configured_member1_adapter_replaces_fallback():
    result = analyze_label_text({"raw_text": LABEL}, Member1())
    assert result["ingredients"] == ["normalized oats"]
    assert result["integration"] == {"status": "available", "provider": "member_1_test"}


def test_member2_contract_and_legacy_fallback_are_distinct():
    nlp = analyze_label_text({"raw_text": LABEL})
    configured = predict_health(nlp, predictor=Member2())
    legacy = predict_health(nlp, legacy_scorer=LegacyScorer())
    assert configured["result"]["health_score"] == 68
    assert configured["integration"]["status"] == "available"
    assert legacy["result"] == {
        "legacy_score": 6.5,
        "model_id": "legacy_development_health_score_model",
    }
    assert "not the final" in legacy["warning"]


def test_member2_missing_features_is_graceful():
    result = predict_health({"nutrition": {"fat_100g": 1}})
    assert not result["available"]
    assert result["result"] is None


def test_member5_unavailable_and_configured_behaviors():
    unavailable = explain_analysis({}, None)
    configured = explain_analysis({}, {"health_score": 68}, Member5())
    assert unavailable["result"] is None
    assert unavailable["integration"]["status"] == "not_configured"
    assert configured["result"]["summary"] == "configured explanation"


def test_team_pipeline_returns_partial_when_optional_modules_are_unavailable():
    response = TeamAnalysisPipeline().analyze_text({"raw_text": "Ingredients: oats"})
    assert response.status == "partial_success"
    assert response.analysis["ingredients"] == ["oats"]
    assert response.health is None
    assert response.explanation is None


def test_configured_adapter_failures_degrade_gracefully():
    nlp = analyze_label_text({"raw_text": LABEL}, BrokenAdapter())
    health = predict_health(nlp, predictor=BrokenAdapter())
    explanation = explain_analysis(nlp, None, BrokenAdapter())
    assert nlp["integration"]["status"] == "fallback"
    assert health["integration"]["status"] == "error"
    assert explanation["integration"]["status"] == "error"


def test_legacy_scorer_rejects_non_100g_basis_even_with_complete_keys():
    nutrition = analyze_label_text(
        {"raw_text": LABEL.replace("Per 100 g", "Per serving")}
    )
    result = predict_health(nutrition, legacy_scorer=LegacyScorer())
    assert result["available"] is False
