"""R3-to-R4 evidence must retain modality rather than invent allergen presence."""

import pytest

from ai.food_understanding.extraction import extract_ingredients
from ai.food_understanding.schemas import (
    Box,
    DetectionMethod,
    IngredientExtraction,
    OCRLine,
    Region,
)
from ai.ingredient_intelligence.service import IngredientIntelligenceService
from ai.ingredient_intelligence.taxonomy import load_runtime_bundle


@pytest.fixture(scope="module")
def service() -> IngredientIntelligenceService:
    return IngredientIntelligenceService(
        *load_runtime_bundle("data/runtime/r4-taxonomies-v0.1.0.json.gz")
    )


def _extract(statement: str, ingredients: str = "Water, rice") -> IngredientExtraction:
    region = Region(
        region_id="ingredients",
        region_type="ingredient_list",
        bounding_box=Box(x=0, y=0, width=400, height=100),
        method=DetectionMethod.OCR_LAYOUT,
        source_view_id="test",
    )
    return extract_ingredients(
        [
            OCRLine(
                text=f"Ingredients: {ingredients}",
                bounding_box=Box(x=10, y=10, width=300, height=20),
            ),
            OCRLine(text=statement, bounding_box=Box(x=10, y=40, width=300, height=20)),
            OCRLine(text="Net Quantity: 200 g", bounding_box=Box(x=10, y=70, width=300, height=20)),
        ],
        region,
    )


@pytest.mark.parametrize(
    "statement",
    [
        "May contain: Milk, Soy",
        "May also contain milk and peanuts",
        "Might contain soy",
        "Contains no milk",
        "Does not contain peanuts",
        "Doesn't contain milk",
        "Free from milk",
        "Milk-free",
        "Allergen: No milk",
        "Allergen:- May contain Milk",
        "Allergen : - Contains no Milk",
        "Allergen information: Without milk",
        "Allergen: Contains milk; may contain soy",
        "Traces of soy",
    ],
)
def test_qualified_statements_survive_r3_and_never_become_positive(
    service: IngredientIntelligenceService, statement: str
) -> None:
    extraction = _extract(statement)
    assert extraction.allergen_text == statement
    assert extraction.raw_text == "Water, rice"
    result = service.analyze(extraction)
    assert not any(item.allergen.matched for item in result.allergens)
    declarations = [
        item.allergen
        for item in result.allergens
        if item.allergen.evidence_source == "PACKAGE_ALLERGEN_STATEMENT_OCR"
    ]
    assert len(declarations) == 1
    assert declarations[0].evidence_text == statement
    assert declarations[0].match_method == "UNRESOLVED_QUALIFIED_STATEMENT"
    assert result.warnings


@pytest.mark.parametrize(
    "statement",
    [
        "Contains: Milk",
        "CONTAINS MILK",
        "Allergen: Contains Milk",
        "Allergen Information: Milk",
        "Alergen:- CONTAINS MILK",
        "Allergen : - Contains: Milk",
    ],
)
def test_affirmative_statement_is_resolved_with_original_provenance(
    service: IngredientIntelligenceService, statement: str
) -> None:
    extraction = _extract(statement)
    assert extraction.allergen_text == statement
    result = service.analyze(extraction)
    positives = [item.allergen for item in result.allergens if item.allergen.matched]
    assert len(positives) == 1
    assert positives[0].canonical_name == "milk"
    assert positives[0].match_method == "EXPLICIT_STATEMENT"
    assert positives[0].evidence_text == statement
    assert positives[0].evidence_source == "PACKAGE_ALLERGEN_STATEMENT_OCR"


def test_affirmative_multiple_allergens_keeps_governed_identity(
    service: IngredientIntelligenceService,
) -> None:
    result = service.analyze(_extract("Contains: Milk and Soy"))
    assert {item.allergen.canonical_name for item in result.allergens if item.allergen.matched} == {
        "milk",
        "soybeans",
    }


def test_negative_statement_does_not_erase_ingredient_evidence(
    service: IngredientIntelligenceService,
) -> None:
    result = service.analyze(_extract("Contains no milk", ingredients="Milk, rice"))
    positives = [item.allergen for item in result.allergens if item.allergen.matched]
    assert len(positives) == 1
    assert positives[0].canonical_name == "milk"
    assert positives[0].match_method == "EXACT"
    assert positives[0].evidence_source == "INGREDIENT_TAXONOMY"
    assert positives[0].evidence_text == "Milk"
    assert any(
        item.allergen.evidence_text == "Contains no milk" and not item.allergen.matched
        for item in result.allergens
    )


@pytest.mark.parametrize("statement", ["MILK", "milk, soy", "Contains: Milk " + "x" * 2000])
def test_ambiguous_legacy_or_oversized_statement_stays_unresolved(
    service: IngredientIntelligenceService, statement: str
) -> None:
    result = service.analyze(IngredientExtraction(raw_text="Water", allergen_text=statement))
    assert not any(item.allergen.matched for item in result.allergens)
    assert any(item.allergen.evidence_text == statement for item in result.allergens)


def test_same_line_ingredient_boundary_preserves_precaution(
    service: IngredientIntelligenceService,
) -> None:
    extraction = extract_ingredients(
        [
            OCRLine(
                text="Ingredients: Rice. May contain Milk, Soy",
                bounding_box=Box(x=10, y=10, width=300, height=20),
            )
        ],
        Region(
            region_id="ingredients",
            region_type="ingredient_list",
            bounding_box=Box(x=0, y=0, width=400, height=100),
            method=DetectionMethod.OCR_LAYOUT,
            source_view_id="test",
        ),
    )
    assert extraction.allergen_text == "May contain Milk, Soy"
    assert "May" not in extraction.raw_text
    assert not any(item.allergen.matched for item in service.analyze(extraction).allergens)
