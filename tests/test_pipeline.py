import io

from PIL import Image

from backend.app.ocr.extractor import OcrResult
from backend.app.ocr.preprocessing import PreparedImage
from backend.app.ocr.service import OcrExecution
from backend.app.services import pipeline as pipeline_module
from backend.app.services.pipeline import ImageAnalysisPipeline


def png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (600, 900), "white").save(output, "PNG")
    return output.getvalue()


def execution(result):
    return OcrExecution(result, PreparedImage(Image.new("L", (600, 900)), 600, 900, True))


FULL_LABEL = """Nutrition per 100 g
Energy 840 kJ
Total fat 10 g
Saturated fat 3 g
Sugars 12 g
Fiber 2 g
Protein 5 g
Salt 0.5 g
Sodium 200 mg
Ingredients: oats, sugar, salt"""

SUGAR_LABEL = """Nutrition Information
Value Per 100 g
Energy (Kcal) 399.3
Total Fat (g) 0
Saturated Fat (g) 0
Sodium (mg) 1.13
Total Carbohydrate (g) 99.92
Dietary Fibre (g) 0
Total Sugar (g) 99.91
Protein (g) 0
Ingredient: Refined Cane Sugar"""


class FakeScorer:
    def __init__(self): self.features = None
    def predict(self, features): self.features = features; return 6.25


class FakeExtension:
    key = "xai"
    provider = "member_5_test_adapter"

    def analyze(self, context):
        return {"received_score": context.health_score}


def test_complete_pipeline_calls_ocr_parser_ingredients_and_scoring(monkeypatch):
    monkeypatch.setattr(
        pipeline_module,
        "execute_ocr",
        lambda *args, **kwargs: execution(OcrResult(FULL_LABEL, "tesseract", "eng", 92.0)),
    )
    scorer = FakeScorer()
    result = ImageAnalysisPipeline(scorer=scorer).analyze(png_bytes(), "image/png", True)
    assert result.status == "success"
    assert result.health_score.value == 6.25
    assert result.ingredients == ["oats", "sugar", "salt"]
    assert scorer.features["sodium_100g"] == 0.2
    assert result.raw_text == FULL_LABEL


def test_sideways_sugar_label_remains_partial_and_reports_rotation(monkeypatch):
    monkeypatch.setattr(
        pipeline_module,
        "execute_ocr",
        lambda *args, **kwargs: execution(OcrResult(
            SUGAR_LABEL,
            "tesseract",
            "eng",
            81.4,
            selected_rotation=90,
            selected_psm=6,
            candidate_count=5,
        )),
    )
    scorer = FakeScorer()
    result = ImageAnalysisPipeline(scorer=scorer).analyze(png_bytes(), "image/png")
    assert result.status == "partial"
    assert result.ocr.selected_rotation == 90
    assert result.ocr.selected_psm == 6
    assert result.ingredients == ["Refined Cane Sugar"]
    assert result.normalized_nutrition["energy_100g"] == 1670.6712
    assert result.normalized_nutrition["sodium_100g"] == 0.00113
    assert result.missing_required_fields == ["salt_100g"]
    assert not result.health_score.performed
    assert scorer.features is None


def test_partial_pipeline_does_not_score_missing_fields(monkeypatch):
    monkeypatch.setattr(
        pipeline_module,
        "execute_ocr",
        lambda *args, **kwargs: execution(OcrResult("per 100 g\nSugars 4 g", "tesseract", "eng", None)),
    )
    scorer = FakeScorer()
    result = ImageAnalysisPipeline(scorer=scorer).analyze(png_bytes(), "image/png")
    assert result.status == "partial"
    assert not result.health_score.performed
    assert scorer.features is None
    assert "fat_100g" in result.missing_required_fields
    assert result.integrations["rag"].status == "not_configured"


def test_pipeline_exposes_only_explicit_fallback_allergens(monkeypatch):
    label = "Ingredients: pasteurized cow milk\nAllergen: CONTAINS MILK"
    monkeypatch.setattr(
        pipeline_module,
        "execute_ocr",
        lambda *args, **kwargs: execution(OcrResult(label, "tesseract", "eng", 90.0)),
    )
    result = ImageAnalysisPipeline(scorer=FakeScorer()).analyze(png_bytes(), "image/png")
    assert result.allergens == ["Milk"]


def test_optional_team_extension_uses_stable_context(monkeypatch):
    monkeypatch.setattr(
        pipeline_module,
        "execute_ocr",
        lambda *args, **kwargs: execution(OcrResult(FULL_LABEL, "tesseract", "eng", 90.0)),
    )
    result = ImageAnalysisPipeline(
        scorer=FakeScorer(), extensions=(FakeExtension(),)
    ).analyze(png_bytes(), "image/png")
    assert result.integrations["xai"].status == "available"
    assert result.extensions["xai"] == {"received_score": 6.25}
