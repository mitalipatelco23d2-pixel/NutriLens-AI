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
