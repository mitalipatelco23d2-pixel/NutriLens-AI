"""Generic regression tests for OCR ingredient line joining logic.

Verifies:
- Wrapped ingredient names across lines are joined with space
- Delimited lines (comma, semicolon) are preserved
- Distinct unpunctuated lines are not merged into single phrases
- Colon headings are handled
- Parenthesized subingredients across lines are joined
- Percentage and spec values across lines are joined
- Bullet points are handled
- Single-line, empty, and noisy OCR inputs are handled gracefully
"""

from __future__ import annotations

from ai.food_understanding.extraction import _join_ingredient_lines


def test_join_wrapped_adjective_noun_phrase() -> None:
    """e.g. 'Pasteurized' on line 1, 'Cow Milk' on line 2."""
    lines = ["Pasteurized", "Cow Milk"]
    assert _join_ingredient_lines(lines) == "Pasteurized Cow Milk"


def test_join_wrapped_multi_word_ingredient() -> None:
    """e.g. 'Whole Wheat' on line 1, 'Flour (60%),' on line 2."""
    lines = ["Whole Wheat", "Flour (60%),", "Filtered", "Water,", "Iodized Salt"]
    result = _join_ingredient_lines(lines)
    assert result == "Whole Wheat Flour (60%), Filtered Water, Iodized Salt"


def test_distinct_unpunctuated_lines_not_merged() -> None:
    """Distinct unpunctuated ingredients must not merge into one."""
    lines = ["Sugar", "Palm Oil", "Salt"]
    result = _join_ingredient_lines(lines)
    assert result == "Sugar, Palm Oil, Salt"
    assert "Sugar Palm Oil" not in result


def test_comma_ended_lines_preserved() -> None:
    lines = ["Water,", "Sugar,", "Salt"]
    assert _join_ingredient_lines(lines) == "Water, Sugar, Salt"


def test_semicolon_ended_lines_preserved() -> None:
    lines = ["Milk Solids;", "Sugar;", "Cocoa Butter"]
    assert _join_ingredient_lines(lines) == "Milk Solids; Sugar; Cocoa Butter"


def test_colon_heading_stripped_or_separated() -> None:
    lines = ["Ingredients:", "Pasteurized Cow Milk"]
    assert _join_ingredient_lines(lines) == "Pasteurized Cow Milk"


def test_parenthesized_subingredients_across_lines() -> None:
    lines = [
        "Enriched Flour (Wheat Flour,",
        "Niacin, Reduced Iron,",
        "Thiamine Mononitrate),",
        "Water,",
        "Sugar",
    ]
    result = _join_ingredient_lines(lines)
    assert "Wheat Flour, Niacin, Reduced Iron, Thiamine Mononitrate)" in result
    assert result.startswith("Enriched Flour (Wheat Flour, Niacin")


def test_percentage_spec_values_across_lines() -> None:
    lines = ["Milk Fat (min.", "1.5%),", "Milk Solids Not Fat (min.", "8.5%)"]
    result = _join_ingredient_lines(lines)
    assert "Milk Fat (min. 1.5%)," in result
    assert "Milk Solids Not Fat (min. 8.5%)" in result


def test_bullet_points_converted_to_delimited_list() -> None:
    lines = ["• Rolled Oats", "• Raw Honey", "• Crushed Almonds"]
    result = _join_ingredient_lines(lines)
    assert "Rolled Oats, Raw Honey, Crushed Almonds" in result


def test_single_line_ingredient() -> None:
    lines = ["100% Pure Organic Honey"]
    assert _join_ingredient_lines(lines) == "100% Pure Organic Honey"


def test_empty_lines_and_whitespace_ignored() -> None:
    lines = ["", "  ", "\t"]
    assert _join_ingredient_lines(lines) == ""


def test_ocr_garbage_and_trailing_punctuation() -> None:
    lines = ["Sugar,", "  , ", "Palm Oil;", " ; ; "]
    result = _join_ingredient_lines(lines)
    assert "Sugar" in result and "Palm Oil" in result


def test_lowercase_distinct_ingredients_and_prefixes_are_not_joined():
    assert _join_ingredient_lines(["sugar", "salt", "organic oats"]) == "sugar, salt, organic oats"
    assert _join_ingredient_lines(["Water", "Orange peel"]) == "Water, Orange peel"


def test_allergen_heading_is_not_joined_into_ingredients():
    from ai.food_understanding.extraction import extract_ingredients
    from ai.food_understanding.schemas import Box, DetectionMethod, OCRLine, Region

    region = Region(
        region_id="ingredients",
        region_type="ingredient_list",
        bounding_box=Box(x=0, y=0, width=300, height=300),
        method=DetectionMethod.OCR_LAYOUT,
        source_view_id="label",
    )
    lines = [
        OCRLine(text=value, bounding_box=Box(x=10, y=10 + i * 30, width=200, height=20))
        for i, value in enumerate(["Ingredients:", "Pasteurized", "Cow Milk", "Contains Milk"])
    ]
    result = extract_ingredients(lines, region)
    assert result.raw_text == "Pasteurized Cow Milk"
    assert result.allergen_text == "Contains Milk"
