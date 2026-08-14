import pytest

from backend.app.ocr.extractor import OcrWord
from backend.app.ocr.geometry import normalize_polygon
from backend.app.ocr.nutrition_parser import parse_nutrition_text


def token(text, x, baseline_y, width=60, height=24, slope=0.08, line=1):
    top = round(baseline_y + slope * x - height / 2)
    return OcrWord(text, 90, x, top, width, height, 1, 1, line)


def synthetic_table(style):
    words = [
        token("Value", 80, 20), token("Per", 160, 20), token("100g", 300, 20),
        token("RDA%", 500, 20),
    ]
    rows = [
        (100, ("Energy", "(Kcal)"), "399.3", "19.9"),
        (160, ("Total", "Fat", "(g)"), "0", "0"),
        (220, ("Saturated", "Fat", "(g)"), "0", "0"),
        (280, ("Sodium", "(mg)"), "1.13", "0.0056"),
        (340, ("Total", "Carbohydrate", "(g)"), "99.92", "20"),
        (400, ("Dietary", "Fibre", "(g)"), "0", "0"),
        (460, ("Total", "Sugar", "(g)"), "20", "4"),
        (520, ("Protein", "(g)"), "2", "1"),
    ]
    for line, (baseline, label, value, rda) in enumerate(rows, start=2):
        if style == "polygon":
            split = max(1, len(label) - 1)
            words.append(token(" ".join(label[:split]), 40, baseline, width=120, height=34, line=line))
            words.append(token(" ".join(label[split:]), 180, baseline, width=65, height=32, line=line))
        else:
            x = 40
            for part in label:
                words.append(token(part, x, baseline, width=max(35, len(part) * 9), line=line))
                x += max(35, len(part) * 9) + 8
        words.append(token(value, 300, baseline, width=max(24, len(value) * 12), line=line))
        words.append(token(rda, 500, baseline, width=max(24, len(rda) * 12), line=line))
    return words


def test_polygon_box_normalizes_to_rectangle():
    bounds = normalize_polygon([[12, 8], [92, 10], [90, 42], [10, 40]])
    assert (bounds.x_min, bounds.y_min, bounds.x_max, bounds.y_max) == (10, 8, 92, 42)
    assert bounds.center_x == 51
    assert bounds.center_y == 25


def test_crop_and_resize_transform_remains_in_one_coordinate_space():
    bounds = normalize_polygon(
        [[20, 30], [60, 30], [60, 50], [20, 50]],
        scale_x=2,
        scale_y=3,
        offset_x=100,
        offset_y=200,
    )
    assert (bounds.x_min, bounds.y_min, bounds.x_max, bounds.y_max) == (140, 290, 220, 350)


def test_rectangle_and_polygon_box_styles_parse_equivalently():
    tesseract = parse_nutrition_text("Value Per 100 g", synthetic_table("tesseract"))
    polygon = parse_nutrition_text("Value Per 100 g", synthetic_table("polygon"))
    assert tesseract.normalized_model_values == polygon.normalized_model_values
    assert polygon.nutrients["energy_100g"].source_value == 399.3
    assert polygon.nutrients["carbohydrates_100g"].value == 99.92
    assert polygon.nutrients["fiber_100g"].value == 0


def test_numeric_value_cannot_jump_to_neighboring_row():
    words = synthetic_table("polygon")
    words = [
        word for word in words
        if not (word.text == "0" and 390 <= word.center_y - 0.08 * word.center_x <= 410)
    ]
    result = parse_nutrition_text("Value Per 100 g", words)
    assert result.nutrients["carbohydrates_100g"].value == 99.92
    assert "fiber_100g" not in result.nutrients


def test_missing_primary_value_does_not_fall_through_to_rda_column():
    words = synthetic_table("polygon")
    words = [
        word for word in words
        if not (word.text == "0" and word.center_x < 400 and 210 <= word.center_y - 0.08 * word.center_x <= 230)
    ]
    result = parse_nutrition_text("Value Per 100 g", words)
    assert "saturated_fat_100g" not in result.nutrients


def test_multi_box_label_reconstruction_survives_sloped_rows():
    result = parse_nutrition_text("Value Per 100 g", synthetic_table("tesseract"))
    assert result.nutrients["saturated_fat_100g"].value == 0
    assert result.nutrients["sodium_100g"].source_value == 1.13
    assert result.nutrients["sodium_100g"].value == pytest.approx(0.00113)


def test_curved_rows_use_local_value_association_and_keep_rda_separate():
    words = [
        token("Amount", 40, 20, slope=0), token("per", 170, 20, slope=0),
        token("100q", 300, 20, slope=0), token("%RDA", 500, 20, slope=0),
    ]
    rows = [
        (100, ("Energy", "kcal"), "313", "15.6%"),
        (160, ("Total", "Fat", "g"), "<0.5g", "0.7%"),
        (220, ("Trans", "Fat", "g"), "0q", "0%"),
        (280, ("Carbohydrates", "g"), "45g", "15%"),
        (340, ("Sugar", "g"), "2.5g", ""),
        (400, ("Protein", "g"), "22g", ""),
    ]
    for line, (baseline, labels, value, rda) in enumerate(rows, start=2):
        x = 35
        for label in labels:
            words.append(token(label, x, baseline, width=max(35, len(label) * 9), slope=0, line=line))
            x += max(35, len(label) * 9) + 7
        words.append(token(value, 300, baseline + 18, width=58, slope=0, line=line))
        if rda:
            words.append(token(rda, 500, baseline + 25, width=58, slope=0, line=line))
    result = parse_nutrition_text("Nutritional Information\nAmount per 100q", words)
    assert result.nutrients["energy_100g"].source_value == 313
    assert result.nutrients["fat_100g"].value == 0.5
    assert result.nutrients["fat_100g"].qualifier == "less_than"
    assert result.nutrients["trans_fat_100g"].value == 0
    assert result.nutrients["carbohydrates_100g"].value == 45
    assert result.nutrients["sugars_100g"].value == 2.5
    assert result.nutrients["proteins_100g"].value == 22
    assert result.nutrients["energy_100g"].source_value != 15.6
