import pytest

from backend.app.nlp.additives import extract_additives
from backend.app.nlp.allergens import extract_allergen_declarations, extract_explicit_allergens
from backend.app.nlp.ingredients import extract_ingredient_section, extract_ingredients_from_text
from backend.app.services.team_contracts import analyze_label_text


def test_complex_ingredients_preserve_nested_subingredients():
    text = "Ingredients: Potatoes, Vegetable Oil (Sunflower, Corn and/or Canola Oil), Salt"
    assert extract_ingredients_from_text(text) == [
        "Potatoes",
        "Vegetable Oil (Sunflower, Corn and/or Canola Oil)",
        "Salt",
    ]


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("COMPOSITION wheat flour; sugar; salt", ["wheat flour", "sugar", "salt"]),
        ("Made with oats, cocoa", ["oats", "cocoa"]),
        ("INGREDIENTS\nPotatoes,\nVegetable Oil,\nSalt", ["Potatoes", "Vegetable Oil", "Salt"]),
    ],
)
def test_ingredient_heading_variants_and_fragmented_lines(heading, expected):
    assert extract_ingredients_from_text(heading) == expected


def test_fragmented_heading_and_clear_newline_list_are_recovered_without_guessing_text():
    assert extract_ingredients_from_text(
        "INGRE\nDIENTS\nPotatoes\nVegetable Oil\nSalt\nNutrition Facts"
    ) == ["Potatoes", "Vegetable Oil", "Salt"]


def test_contains_inside_subingredient_does_not_end_ingredient_section():
    assert extract_ingredients_from_text(
        "Ingredients: seasoning (contains wheat), potatoes; Contains: Milk"
    ) == ["seasoning (contains wheat)", "potatoes"]


def test_ingredient_percentages_and_additive_codes_are_preserved():
    result = extract_ingredient_section("Ingredients  Cocoa 20%; emulsifier E 322; salt")
    assert result.ingredients == ["Cocoa 20%", "emulsifier E 322", "salt"]
    assert result.truncated is False


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("colour E100", ["E100"]),
        ("colour E 100", ["E100"]),
        ("colour E-100", ["E100"]),
        ("flavour enhancer INS-621", ["Flavour enhancer", "INS 621"]),
        ("preservative; emulsifier; stabiliser; antioxidant", ["Preservative", "Emulsifier", "Stabilizer", "Antioxidant"]),
        ("artificial color and acidity regulator", ["Artificial colour", "Acidity regulator"]),
    ],
)
def test_additive_normalization(text, expected):
    assert extract_additives(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Amount per 100 g",
        "Net weight 100 g",
        "reference e100 for feedback",
    ],
)
def test_nutrition_quantities_and_unrelated_ocr_do_not_become_e100(text):
    assert extract_additives(text) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ingredients: cocoa, emulsifier E 322, salt", ["Emulsifier", "E322"]),
        ("Additives: E-100", ["E100"]),
        ("Colour E100", ["E100"]),
    ],
)
def test_genuine_e_numbers_require_clear_additive_context(text, expected):
    assert extract_additives(text) == expected


def test_negated_named_additive_claims_are_not_reported_as_present():
    assert extract_additives("No artificial colours or preservatives. Colour E 100") == [
        "E100"
    ]


def test_definite_allergens_are_normalized():
    assert extract_explicit_allergens("Contains: Milk, Soy, Wheat and sesame") == [
        "Milk", "Soy", "Wheat", "Sesame"
    ]


def test_precautionary_and_facility_allergens_keep_declaration_type():
    declarations = extract_allergen_declarations(
        "May contain peanuts. Processed in a facility that also handles nuts."
    )
    assert [(item.name, item.declaration) for item in declarations] == [
        ("Peanut", "may_contain"),
        ("Tree Nuts", "facility"),
    ]


def test_allergen_information_prefix_and_crustacean_alias():
    assert extract_explicit_allergens(
        "Allergen Information: Contains Egg, crustaceans"
    ) == ["Egg", "Shellfish"]


def test_unrelated_food_words_are_not_allergen_declarations():
    assert extract_explicit_allergens(
        "Milk production date follows the batch code. Soy Road, Example City."
    ) == []


@pytest.mark.parametrize(
    "text",
    [
        "Does not contain milk",
        "Contains no milk",
        "Allergen Information: Does not contain milk",
    ],
)
def test_negated_allergen_phrases_do_not_create_false_positives(text):
    assert extract_explicit_allergens(text) == []


def test_flexible_spacing_does_not_turn_may_contain_into_definite_contains():
    declarations = extract_allergen_declarations("May   contain peanuts")
    assert [(item.name, item.declaration) for item in declarations] == [
        ("Peanut", "may_contain")
    ]


def test_per_100g_nutrition_canonical_values_and_source_metadata():
    result = analyze_label_text({"raw_text": """Nutrition Information
Values per 100 g
Energy 200 kcal
Total Fat 10 g
Sodium 250 mg"""})
    assert result["basis"] == "per_100g"
    assert result["nutrition"]["energy_kcal_100g"] == 200
    assert result["nutrition"]["energy_kj_100g"] == pytest.approx(836.8)
    assert result["nutrition"]["sodium_100g"] == pytest.approx(0.25)
    assert result["nutrition_details"]["sodium_100g"]["source_unit"] == "mg"
    assert result["nutrition_details"]["energy_kcal_100g"]["unit"] == "kcal"


def test_per_100ml_is_preserved_and_not_silently_relabelled_as_model_basis():
    result = analyze_label_text({"raw_text": "Nutrition Facts\nPer 100 ml\nSodium 45 mg"})
    assert result["basis"] == "per_100ml"
    assert result["nutrition"]["sodium_100g"] == pytest.approx(0.045)
    assert result["nutrition_details"]["sodium_100g"]["basis"] == "per_100ml"
    assert result["nutrition_details"]["sodium_100g"]["source_value"] == 45


def test_per_serving_basis_is_preserved():
    result = analyze_label_text({"raw_text": "Nutrition Facts\nAmount per serving\nTotal Fat 5 g"})
    assert result["basis"] == "per_serving"
    assert result["nutrition_details"]["fat_100g"]["basis"] == "per_serving"


@pytest.mark.parametrize("unit", ["mcg", "µg", "ug"])
def test_micrograms_normalize_safely_to_grams(unit):
    result = analyze_label_text(
        {"raw_text": f"Nutrition Information\nper 100 g\nSodium 500 {unit}"}
    )
    assert result["nutrition"]["sodium_100g"] == pytest.approx(0.0005)
    assert result["nutrition_details"]["sodium_100g"]["source_unit"] == "mcg"


def test_zero_is_preserved_but_missing_values_are_not_created():
    result = analyze_label_text(
        {"raw_text": "Nutrition Information\nper 100 g\nTrans Fat 0 g"}
    )
    assert result["nutrition"]["trans_fat_100g"] == 0
    assert "sugars_100g" not in result["nutrition"]


def test_ambiguous_leading_zero_is_omitted_instead_of_becoming_nine():
    result = analyze_label_text(
        {"raw_text": "Nutrition Information\nper 100 ml\nTotal Fat 09 g"}
    )
    assert "fat_100g" not in result["nutrition"]
    assert any("no reliable decimal separator" in warning for warning in result["warnings"])


def test_rda_percentage_is_not_used_as_nutrient_amount():
    result = analyze_label_text(
        {"raw_text": "Nutrition Information\nper 100 g\nTotal Fat 1.5 g 6%"}
    )
    assert result["nutrition"]["fat_100g"] == 1.5


def test_conflicting_multi_basis_columns_are_omitted_instead_of_assigned():
    result = analyze_label_text(
        {
            "raw_text": "Nutrition Facts\nPer serving  Per 100 g\nTotal Fat 5 g 10 g"
        }
    )
    assert result["basis"] == "unknown"
    assert result["nutrition"] == {}
    assert any("Multiple nutrition bases" in warning for warning in result["warnings"])


def test_duplicate_conflicting_nutrient_rows_are_omitted():
    result = analyze_label_text(
        {"raw_text": "Nutrition Information\nPer 100 g\nTotal Fat 5 g\nTotal Fat 6 g"}
    )
    assert "fat_100g" not in result["nutrition"]
    assert any("conflicting OCR values" in warning for warning in result["warnings"])


def test_consistent_kj_and_kcal_energy_values_are_accepted():
    result = analyze_label_text(
        {"raw_text": "Nutrition Information\nPer 100 g\nEnergy 840 kJ 200 kcal"}
    )
    assert result["nutrition"]["energy_kj_100g"] == 840
    assert result["nutrition"]["energy_kcal_100g"] == pytest.approx(200.764818)


def test_per_serving_values_are_not_validated_as_if_they_were_per_100g():
    result = analyze_label_text(
        {"raw_text": "Nutrition Facts\nAmount per serving\nTotal Fat 120 g"}
    )
    assert result["basis"] == "per_serving"
    assert result["nutrition"]["fat_100g"] == 120
    assert result["nutrition_details"]["fat_100g"]["basis"] == "per_serving"


def test_ocr_line_fallback_and_confidence_metadata_are_preserved():
    result = analyze_label_text(
        {
            "raw_text": None,
            "lines": [{"text": "Ingredients: oats, salt", "confidence": 0.4}],
            "mean_confidence": 0.4,
        }
    )
    assert result["ingredients"] == ["oats", "salt"]
    assert result["metadata"]["text_source"] == "lines"
    assert result["metadata"]["ocr_mean_confidence"] == 0.4
    assert any("OCR confidence was low" in warning for warning in result["warnings"])


def test_low_confidence_incomplete_ocr_does_not_fabricate_structured_fields():
    result = analyze_label_text(
        {
            "raw_text": "shipping weight 100 g\nreference e100\nblurred package text",
            "mean_confidence": 0.31,
        }
    )
    assert result["ingredients"] == []
    assert result["additives"] == []
    assert result["nutrition"] == {}
    assert result["basis"] == "unknown"


def test_sugar_packet_regression_fixture():
    result = analyze_label_text({"raw_text": """Nutrition Information
Value Per 100 g
Energy 399.3 kcal
Total Fat 0 g
Saturated Fat 0 g
Trans Fat 0 g
Sodium 1.13 mg
Total Carbohydrate 99.92 g
Dietary Fibre 0 g
Protein 0 g
Ingredient: Refined Cane Sugar"""})
    assert result["ingredients"] == ["Refined Cane Sugar"]
    assert result["nutrition"]["energy_kcal_100g"] == 399.3
    assert "sugars_100g" not in result["nutrition"]


def test_coffee_jar_regression_fixture_preserves_less_than():
    result = analyze_label_text({"raw_text": """Nutritional Information
Amount per 100g
Energy 313 kcal
Total Fat <0.5 g
Trans Fat 0 g
Carbohydrates 45 g
Sugar 2.5 g
Protein 22 g
Ingredients: Soluble Coffee Powder, Arabica Coffee"""})
    assert result["nutrition"]["fat_100g"] == 0.5
    assert result["nutrition_details"]["fat_100g"]["qualifier"] == "less_than"
    assert result["ingredients"] == ["Soluble Coffee Powder", "Arabica Coffee"]


def test_milk_pouch_regression_does_not_hallucinate_ingredient_or_nutrients():
    result = analyze_label_text({"raw_text": """Nutrition Facts
Per 100 ml
Sodium 45 mg
Ingredient: asteurized Cow Milk
Allergen: CONTAINS MILK"""})
    assert result["basis"] == "per_100ml"
    assert result["nutrition"] == {"sodium_100g": pytest.approx(0.045)}
    assert result["ingredients"] == ["asteurized Cow Milk"]
    assert result["allergens"] == ["Milk"]


def test_us_chips_label_calories_and_per_serving_fixture():
    result = analyze_label_text({"raw_text": """Nutrition Facts
Amount per serving
Calories 160
Total Fat 10 g 13%
Saturated Fat 1.5 g 8%
Sodium 170 mg 7%
Total Carbohydrate 15 g 5%
Protein 2 g
Ingredients: Potatoes, Vegetable Oil, Salt
Contains: Milk"""})
    assert result["basis"] == "per_serving"
    assert result["nutrition"]["energy_kcal_100g"] == 160
    assert result["nutrition"]["fat_100g"] == 10
    assert result["nutrition"]["sodium_100g"] == pytest.approx(0.17)
    assert result["ingredients"] == ["Potatoes", "Vegetable Oil", "Salt"]
    assert result["allergens"] == ["Milk"]
