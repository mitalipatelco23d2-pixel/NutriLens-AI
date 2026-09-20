import pytest

from backend.app.nlp.ingredients import extract_ingredient_section
from backend.app.nlp.parser import FallbackIngredientExtractor, extract_ingredients_from_text


def test_simple_ingredient_list():
    assert extract_ingredients_from_text("Ingredients: flour, sugar, salt. Nutrition Facts") == [
        "flour", "sugar", "salt"
    ]


def test_multiline_ingredient_list():
    text = "Ingredients: wheat flour,\nsugar, palm oil\nNutrition information"
    assert extract_ingredients_from_text(text) == ["wheat flour", "sugar", "palm oil"]


def test_unicode_is_preserved():
    assert extract_ingredients_from_text("Ingredients: jalapeño, crème fraîche, azúcar") == [
        "jalapeño", "crème fraîche", "azúcar"
    ]


def test_allergen_only_contains_statement_is_not_an_ingredient_list():
    assert extract_ingredients_from_text("Contains: milk, soy") == []


def test_nested_subingredients_remain_grouped():
    assert extract_ingredients_from_text("Ingredients: whey powder (milk, soy), sugar") == [
        "whey powder (milk, soy)", "sugar"
    ]


def test_fallback_implements_replaceable_interface():
    assert FallbackIngredientExtractor().extract("Ingredients: oats, salt") == ["oats", "salt"]


def test_singular_ingredient_preserves_label_text():
    assert extract_ingredients_from_text("Ingredient: Refined Cane Sugar") == [
        "Refined Cane Sugar"
    ]


def test_singular_ingredient_stops_before_nearby_marketing_paragraph():
    text = (
        "Ingredient: Refined Cane Sugar\n"
        "Refined sugar is monitored throughout the process. MORE ACIDIC packaging copy."
    )
    assert extract_ingredients_from_text(text) == ["Refined Cane Sugar"]


def test_short_ingredient_statement_stops_before_storage_text():
    text = "Ingredients: coffee powder, chicory\nStorage instructions: keep dry"
    assert extract_ingredients_from_text(text) == ["coffee powder", "chicory"]


def test_ingredient_statement_stops_before_importer_and_manufacturer_sections():
    text = (
        "Ingredients: oats, salt\nImported by Example Foods, 10 Main Road\n"
        "Manufacturer: Example Factory"
    )
    assert extract_ingredients_from_text(text) == ["oats", "salt"]


def test_ingredient_statement_stops_before_nutrition_section():
    text = "Ingredients: milk, cocoa\nNutritional Information\nEnergy 100 kcal"
    assert extract_ingredients_from_text(text) == ["milk", "cocoa"]


def test_multilingual_duplicate_after_complete_english_statement_is_not_swallowed():
    text = (
        "Ingredients: Soluble Coffee Powder, Arabica Coffee\n"
        "Café instantané. Ingredients: Café arabica\nImported by Example"
    )
    assert extract_ingredients_from_text(text) == [
        "Soluble Coffee Powder", "Arabica Coffee"
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Ingredients: oats, cocoa, salt\nNutrition Information",
        "Composition: wheat flour, vegetable oil, salt\nAllergen: contains wheat",
        "Made with: milk solids, sugar, acidity regulator (INS 330)\nBest before: 2027",
        "Ingredients: whey powder (milk, soy), sugar, E322\nNutrition Facts",
    ],
)
def test_explicit_bounded_structural_lists_are_trusted(text):
    result = extract_ingredient_section(text, ocr_confidence=0.91)

    assert result.quality_status == "trusted"
    assert result.boundary_detected is True
    assert result.ingredients


def test_long_bulleted_ingredient_list_is_not_mistaken_for_repeated_heading():
    ingredients = [f"component {index}" for index in range(1, 16)]
    text = "Ingredients:\n" + "\n".join(
        f"- {item}" for item in ingredients
    ) + "\nNutrition Information"

    result = extract_ingredient_section(text, ocr_confidence=0.9)

    assert result.quality_status == "trusted"
    assert result.ingredients == ingredients


def test_low_confidence_but_structural_list_is_partial_not_trusted():
    result = extract_ingredient_section(
        "Ingredients: oats, cocoa\nNutrition Information",
        ocr_confidence=0.31,
    )

    assert result.quality_status == "partial"
    assert any("low OCR confidence" in reason for reason in result.quality_reasons)


def test_incomplete_list_without_reliable_boundary_is_partial():
    result = extract_ingredient_section("Ingredients: oats, cocoa,", ocr_confidence=0.9)

    assert result.quality_status == "partial"
    assert result.truncated is True


@pytest.mark.parametrize(
    "text",
    [
        (
            "Ingredients: Pasteurized Cow Milk, Milk Fat 3.0% Max, "
            "SNF 8.5% Min\nAllergen: contains milk"
        ),
        "Ingredients: Refined Cane Sugar is monitored throughout the process.",
        "Ingredients: oats, salt, MRP 25, customer care 12345",
    ],
)
def test_packaging_specs_or_prose_do_not_become_trusted_ingredients(text):
    result = extract_ingredient_section(text, ocr_confidence=0.9)

    assert result.quality_status == "untrusted"
    assert result.quality_reasons


def test_missing_ingredient_heading_is_explicitly_absent():
    result = extract_ingredient_section(
        "Nutrition Information per 100 g\nEnergy 290 kcal\nNet weight 50 g",
        ocr_confidence=0.9,
    )

    assert result.ingredients == []
    assert result.quality_status == "absent"
