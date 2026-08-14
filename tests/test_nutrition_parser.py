import pytest

from backend.app.ocr.extractor import OcrWord
from backend.app.ocr.nutrition_parser import parse_nutrition_text


def word(text, left, top, line, width=45):
    return OcrWord(text, 90.0, left, top, width, 20, 1, 1, line)


def spatial_sugar_table_words():
    words = [
        word("Value", 30, 10, 1), word("Per", 220, 10, 1),
        word("100", 300, 10, 1), word("g", 355, 10, 1, 15),
    ]
    rows = [
        (2, "Energy", "(Kcal)", ["399", ".", "3"], "8.4"),
        (3, "Total Fat", "(g)", ["0"], "0"),
        (4, "Saturated Fat", "(g)", ["0"], "0"),
        (5, "Sodium", "(mg)", ["1", ".", "13"], "0.1"),
        (6, "Total Carbohydrate", "(g)", ["99", ".", "92"], "20"),
        (7, "Dietary Fibre", "(g)", ["0"], "0"),
        (8, "Total Sugar", "(g)", ["99", ".", "91"], "20"),
        (9, "Added Sugar", "(g)", ["99", ".", "91"], "19.98"),
        (10, "Protein", "(g)", ["0"], "0"),
    ]
    for line, label, unit, pieces, rda in rows:
        top = 10 + line * 30
        x = 20
        for token in label.split():
            words.append(word(token, x, top, line, width=max(35, len(token) * 9)))
            x += max(35, len(token) * 9) + 8
        words.append(word(unit, 185, top, line, 45))
        x = 292
        for piece in pieces:
            width = 15 if piece == "." else max(18, len(piece) * 13)
            words.append(word(piece, x, top, line, width))
            x += width + 2
        words.append(word(rda, 500, top, line, max(25, len(rda) * 11)))
    return words


def spatial_milk_table_words():
    words = [
        word("Nutrition", 20, 10, 1, 80), word("Facts", 108, 10, 1, 50),
        word("Per", 270, 40, 2, 30), word("100 ml", 305, 40, 2, 65),
        word("Per", 455, 40, 2, 30), word("serve", 490, 40, 2, 55),
        word("%RDA", 620, 40, 2, 50),
    ]
    rows = [
        (3, "Iblories", "50 kcal", "125 kcal", "6%"),
        (4, "hoteln", "3.6 g", "9 g", "18%"),
        (5, "larbohydrates", "5.5 g", "14 g", "5%"),
        (6, "Total Sugar", "5.5 g", "14 g", ""),
        (7, "Added Sugar", "0 g", "0 g", "0%"),
        (8, "Total Fat", "1.5 g", "4 g", "6%"),
        (9, "Saturated Fat", "0.9 g", "2.3 g", "10%"),
        (10, "Trans Fat", "0 g", "0 g", "0%"),
        (11, "Cholesterol", "4 mg", "10 mg", ""),
        (12, "Sodium", "45 mg", "112 mg", "6%"),
        (13, "Calcium", "200 mg", "500 mg", "50%"),
    ]
    for line, label, per100, serving, rda in rows:
        top = 40 + line * 30
        words.append(word(label, 20, top, line, max(65, len(label) * 9)))
        words.append(word(per100, 305, top + (line % 2), line, max(45, len(per100) * 9)))
        words.append(word(serving, 485, top + 2, line, max(40, len(serving) * 9)))
        if rda:
            words.append(word(rda, 625, top + 3, line, max(30, len(rda) * 9)))
    return words


def test_full_per_100g_label_separates_total_and_saturated_fat():
    result = parse_nutrition_text(
        """Nutrition per 100 g
        Energy 840 kJ / 200 kcal
        Total Fat 10 g Saturated Fat 3 g
        Sugars 12 g Fiber 2 g Protein 5 g
        Salt 0.5 g Sodium 200 mg"""
    )
    assert result.basis == "per_100g"
    assert result.normalized_model_values == {
        "energy_100g": 840.0,
        "fat_100g": 10.0,
        "saturated_fat_100g": 3.0,
        "sugars_100g": 12.0,
        "fiber_100g": 2.0,
        "proteins_100g": 5.0,
        "salt_100g": 0.5,
        "sodium_100g": 0.2,
    }


def test_energy_per_100g_heading_number_is_not_the_energy_value():
    result = parse_nutrition_text("Energy per 100g 840 kJ")
    assert result.nutrients["energy_100g"].value == 840


def test_kcal_is_converted_to_kilojoules_without_losing_source_unit():
    result = parse_nutrition_text("Values per 100 g\nEnergy 200 kcal")
    energy = result.nutrients["energy_100g"]
    assert energy.value == pytest.approx(836.8)
    assert energy.unit == "kJ"
    assert energy.source_unit == "kcal"


def test_milligrams_are_normalized_to_grams():
    sodium = parse_nutrition_text("per 100 g Sodium 250 mg").nutrients["sodium_100g"]
    assert sodium.value == pytest.approx(0.25)
    assert sodium.source_unit == "mg"


def test_per_serving_values_are_not_model_values():
    result = parse_nutrition_text("Amount per serving\nFat 5 g\nSugars 2 g")
    assert result.basis == "per_serving"
    assert result.normalized_model_values == {}
    assert any("requires per 100 g" in warning for warning in result.warnings)


def test_per_100ml_is_distinguished():
    result = parse_nutrition_text("Typical values per 100 ml\nSugars 4 g")
    assert result.basis == "per_100ml"


def test_three_column_per_100ml_table_uses_one_primary_column_consistently():
    result = parse_nutrition_text(
        "Nutrition Facts\nPer 100 ml\nTotal Fat 9 g\nTotal Sugar 4 g",
        spatial_milk_table_words(),
    )
    expected = {
        "energy_100g": (50, "kcal"),
        "proteins_100g": (3.6, "g"),
        "carbohydrates_100g": (5.5, "g"),
        "sugars_100g": (5.5, "g"),
        "added_sugars_100g": (0, "g"),
        "fat_100g": (1.5, "g"),
        "saturated_fat_100g": (0.9, "g"),
        "trans_fat_100g": (0, "g"),
        "cholesterol_100g": (4, "mg"),
        "sodium_100g": (45, "mg"),
        "calcium_100g": (200, "mg"),
    }
    assert result.basis == "per_100ml"
    assert result.normalized_model_values == {}
    for field, (source_value, source_unit) in expected.items():
        assert result.nutrients[field].source_value == source_value
        assert result.nutrients[field].source_unit == source_unit
    assert result.nutrients["sodium_100g"].value == pytest.approx(0.045)
    assert result.nutrients["calcium_100g"].value == pytest.approx(0.2)
    assert result.nutrients["fat_100g"].source_value != 4
    assert result.nutrients["sugars_100g"].source_value != 14


def test_detached_competing_primary_cell_is_omitted_instead_of_guessed():
    words = [
        word("Nutrition", 20, 10, 1, 80),
        word("Per", 250, 35, 2, 35), word("100", 300, 35, 2, 35), word("ml", 340, 35, 2, 25),
        word("Carbohydrates", 20, 100, 3, 120),
        word("3g", 320, 100, 3, 30),
        word("15", 305, 113, 4, 28),
        word("14g", 480, 102, 3, 40),
    ]
    result = parse_nutrition_text("Nutrition Facts\nPer 100 ml", words)
    assert "carbohydrates_100g" not in result.nutrients


def test_leading_zero_without_decimal_is_not_interpreted_as_whole_grams():
    words = [
        word("Nutrition", 20, 10, 1, 80),
        word("Per", 250, 35, 2, 35), word("100 ml", 300, 35, 2, 65),
        word("Total Fat", 20, 100, 3, 100), word("09g", 310, 100, 3, 40),
    ]
    result = parse_nutrition_text("Nutrition Facts\nPer 100 ml", words)
    assert "fat_100g" not in result.nutrients


def test_multiple_nutrients_on_one_line_are_extracted():
    result = parse_nutrition_text("per 100 g Fat 10 g Saturated fat 3 g Sugars 12 g Protein 5 g")
    assert result.nutrients["fat_100g"].value == 10
    assert result.nutrients["saturated_fat_100g"].value == 3
    assert result.nutrients["sugars_100g"].value == 12
    assert result.nutrients["proteins_100g"].value == 5


def test_common_ocr_letter_o_is_corrected():
    result = parse_nutrition_text("per 100 g Sugars O.5 g")
    assert result.nutrients["sugars_100g"].value == 0.5
    assert any("letter O" in warning for warning in result.warnings)


def test_carbohydrates_are_extracted_but_not_required_by_current_model():
    result = parse_nutrition_text("per 100 g Carbohydrate 45 g")
    assert result.nutrients["carbohydrates_100g"].value == 45
    assert "carbohydrates_100g" not in result.normalized_model_values


def test_unknown_basis_does_not_fabricate_per_100g_values():
    result = parse_nutrition_text("Fat 4 g")
    assert result.basis == "unknown"
    assert result.normalized_model_values == {}


def test_real_sugar_label_parenthesized_units_and_value_per_100g():
    result = parse_nutrition_text(
        """Nutrition Information
        Value Per 100 g
        Energy (Kcal) 399.3
        Total Fat (g) 0
        Saturated Fat (g) 0
        Trans Fat (g) 0
        Sodium (mg) 1.13
        Total Carbohydrate (g) 99.92
        Dietary Fibre (g) 0
        Total Sugar (g) 99.91
        Added Sugar (g) 99.91
        Protein (g) 0"""
    )
    assert result.basis == "per_100g"
    assert result.nutrients["energy_100g"].source_value == 399.3
    assert result.nutrients["energy_100g"].source_unit == "kcal"
    assert result.nutrients["energy_100g"].value == pytest.approx(1670.6712)
    assert result.nutrients["fat_100g"].value == 0
    assert result.nutrients["saturated_fat_100g"].value == 0
    assert result.nutrients["trans_fat_100g"].value == 0
    assert result.nutrients["sodium_100g"].value == pytest.approx(0.00113)
    assert result.nutrients["fiber_100g"].value == 0
    assert result.nutrients["sugars_100g"].value == pytest.approx(99.91)
    assert result.nutrients["added_sugars_100g"].value == pytest.approx(99.91)
    assert result.nutrients["proteins_100g"].value == 0
    assert result.nutrients["carbohydrates_100g"].value == pytest.approx(99.92)
    assert "salt_100g" not in result.normalized_model_values


def test_spatial_table_selects_per_100g_column_and_preserves_split_decimals():
    text = """Nutrition Information\nValue Per 100 g
    Energy (Kcal) 399.3 8.4
    Total Fat (g) 0 0
    Saturated Fat (g) 0 0
    Sodium (mg) 1.13 0.1
    Total Carbohydrate (g) 99.92 20
    Dietary Fibre (g) 0 0
    Total Sugar (g) 99.91 20
    Added Sugar (g) 99.91 19.98
    Protein (g) 0 0"""
    result = parse_nutrition_text(text, spatial_sugar_table_words())
    assert result.nutrients["energy_100g"].value == pytest.approx(1670.6712)
    assert result.nutrients["carbohydrates_100g"].value == pytest.approx(99.92)
    assert result.nutrients["sugars_100g"].value == pytest.approx(99.91)
    assert result.nutrients["added_sugars_100g"].value == pytest.approx(99.91)
    assert result.nutrients["added_sugars_100g"].source_value != 19.98
    assert result.nutrients["sodium_100g"].value == pytest.approx(0.00113)
    for name in ["fat_100g", "saturated_fat_100g", "fiber_100g", "proteins_100g"]:
        assert result.nutrients[name].value == 0


def test_spatial_header_can_be_split_across_ocr_rows_and_corrupted():
    words = [
        word("Value", 30, 10, 1),
        word("Per", 220, 10, 1),
        word("1009", 300, 42, 2),
        word("Per", 490, 10, 1),
        word("RDA", 540, 42, 2),
        word("~aturated", 20, 90, 3, 100),
        word("Fat", 130, 90, 3),
        word("(g)", 190, 90, 3),
        word("0", 305, 90, 3, 18),
        word("25", 520, 90, 3, 25),
        word("fans", 20, 125, 4),
        word("Fat", 75, 125, 4),
        word("(g)", 130, 125, 4),
        word("0", 305, 125, 4, 18),
        word("30", 520, 125, 4, 25),
    ]
    result = parse_nutrition_text("Value Per\n1009", words)
    assert result.basis == "per_100g"
    assert result.nutrients["saturated_fat_100g"].value == 0
    assert result.nutrients["trans_fat_100g"].value == 0


def test_fragmented_primary_cell_is_omitted_instead_of_guessed():
    words = [
        word("Value", 30, 10, 1), word("Per", 220, 10, 1), word("100g", 300, 35, 2),
        word("Added", 20, 90, 3), word("Sugar", 75, 90, 3), word("(g)", 140, 90, 3),
        word("99", 305, 90, 3, width=4), word("9)", 330, 90, 3, width=25),
        word("19.98", 500, 90, 3, width=55),
    ]
    result = parse_nutrition_text("Value Per\n100g\nAdded Sugar (g) 99 9) 19.98", words)
    assert "added_sugars_100g" not in result.nutrients
    assert any("unresolved digit fragments" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    ("text", "field"),
    [
        ("Value Per 100 g\nTotal Sugar (g) 9909", "sugars_100g"),
        ("Value Per 100 g\nAdded Sugar (g) 4998", "added_sugars_100g"),
    ],
)
def test_physically_impossible_gram_values_are_rejected(text, field):
    result = parse_nutrition_text(text)
    assert field not in result.nutrients
    assert any(f"Rejected {field}" in warning for warning in result.warnings)


def test_cross_nutrient_constraints_reject_unsafe_values():
    result = parse_nutrition_text(
        "Value Per 100 g\nTotal Fat (g) 2\nSaturated Fat (g) 3\n"
        "Total Carbohydrate (g) 80\nTotal Sugar (g) 90"
    )
    assert "saturated_fat_100g" not in result.nutrients
    assert "sugars_100g" not in result.nutrients


@pytest.mark.parametrize(
    "header",
    ["100g", "100 g", "100G", "100q", "1009", "1O0g", "IOOg", "100_"],
)
def test_ocr_aware_per_100g_basis_variants_require_header_context(header):
    result = parse_nutrition_text(
        f"Nutritional Information\nAmount per {header}\nEnergy 313 kcal"
    )
    assert result.basis == "per_100g"
    assert result.nutrients["energy_100g"].source_value == 313


@pytest.mark.parametrize("text", ["Price per 100g: 50", "Serial number 1009"])
def test_ocr_aware_basis_is_not_applied_outside_nutrition_context(text):
    assert parse_nutrition_text(text).basis == "unknown"


def test_raw_ocr_nutrition_rows_recover_after_corrupted_split_basis():
    result = parse_nutrition_text(
        "Amount per\n100q\nEnergy 313 kcal\nTotal Fat <0.5g\nProtein 22g"
    )
    assert result.basis == "per_100g"
    assert result.nutrients["energy_100g"].source_value == 313
    assert result.nutrients["proteins_100g"].value == 22


def test_less_than_value_preserves_threshold_and_qualifier():
    result = parse_nutrition_text(
        "Nutrition Information\nAmount per 100g\nTotal Fat <0.5 g"
    )
    fat = result.nutrients["fat_100g"]
    assert fat.value == 0.5
    assert fat.qualifier == "less_than"
    assert any("upper-bound" in warning for warning in result.warnings)


def test_split_ocr_rows_reconstruct_unit_bearing_values_conservatively():
    result = parse_nutrition_text(
        "Nutritional Information\nAmount\nper\nIonq\n"
        "Energy\n313Lcai\nProtein\n22g"
    )
    assert result.basis == "per_100g"
    assert result.nutrients["energy_100g"].source_value == 313
    assert result.nutrients["energy_100g"].source_unit == "kcal"
    assert result.nutrients["proteins_100g"].value == 22
    assert any("kcal unit" in warning for warning in result.warnings)
