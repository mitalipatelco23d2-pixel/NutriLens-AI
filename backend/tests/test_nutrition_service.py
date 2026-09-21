from app.nlp.nutrition_service import (
    clean_nutrition_text,
    detect_serving_basis,
    extract_nutrition,
    extract_nutrient,
    extract_serving_size,
)


def test_extract_nutrition_complete_label():
    text = """
    Nutrition Information
    Energy 480 kcal
    Protein 6 g
    Carbohydrates 70 g
    Total Sugars 25 g
    Total Fat 20 g
    Saturated Fat 10 g
    Trans Fat 0 g
    Dietary Fibre 3 g
    Sodium 400 mg
    Serving Size 50 g
    """

    result = extract_nutrition(text)

    assert result["energy_kcal"] == 480.0
    assert result["protein_g"] == 6.0
    assert result["carbohydrate_g"] == 70.0
    assert result["sugar_g"] == 25.0
    assert result["fat_g"] == 20.0
    assert result["saturated_fat_g"] == 10.0
    assert result["trans_fat_g"] == 0.0
    assert result["fiber_g"] == 3.0
    assert result["sodium_mg"] == 400.0
    assert result["basis"] == "per_serving"
    assert result["serving_size_g"] == 50.0


def test_missing_nutrients_are_not_assumed_zero():
    text = """
    Energy 380 kcal
    Protein 7 g
    """

    result = extract_nutrition(text)

    assert result["energy_kcal"] == 380.0
    assert result["protein_g"] == 7.0

    assert "sugar_g" not in result
    assert "fat_g" not in result
    assert "sodium_mg" not in result


def test_explicit_zero_is_preserved():
    text = """
    Trans Fat 0 g
    Sugar 0 g
    """

    result = extract_nutrition(text)

    assert result["trans_fat_g"] == 0.0
    assert result["sugar_g"] == 0.0


def test_detect_nutrition_basis():
    assert detect_serving_basis("Nutrition per 100 g") == "per_100g"
    assert detect_serving_basis("Nutrition per 100 ml") == "per_100ml"
    assert detect_serving_basis("Nutrition per serving") == "per_serving"
    assert detect_serving_basis("Nutrition Information") == "unknown"


def test_extract_serving_size():
    assert extract_serving_size("Serving Size 50 g") == 50.0
    assert extract_serving_size("Serving Size: 25g") == 25.0
    assert extract_serving_size("Serving 30 grams") == 30.0
    assert extract_serving_size("No serving information") is None


def test_ocr_numeric_correction():
    text = """
    Energy 4O0 kcal
    Sodium 1I0 mg
    """

    cleaned = clean_nutrition_text(text)

    assert "400 kcal" in cleaned
    assert "110 mg" in cleaned


def test_ocr_nutrient_name_correction():
    text = """
    Prote1n 7 g
    Carbohydrat 50 g
    Sodlum 120 mg
    """

    result = extract_nutrition(text)

    assert result["protein_g"] == 7.0
    assert result["carbohydrate_g"] == 50.0
    assert result["sodium_mg"] == 120.0


def test_negative_values_are_rejected():
    patterns = [
        r"\bprotein\b\s*[:\-]?\s*(-\d+(?:\.\d+)?)\s*g\b"
    ]

    result = extract_nutrient("Protein -5 g", patterns)

    assert result is None


def test_invalid_input_is_rejected():
    try:
        extract_nutrition(None)
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert str(exc) == "Nutrition text must be a string."
