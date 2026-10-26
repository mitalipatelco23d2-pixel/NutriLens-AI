from ai.food_understanding.schemas import IngredientExtraction
from ai.ingredient_intelligence.additive_resolver import AdditiveResolver
from ai.ingredient_intelligence.allergen_resolver import AllergenResolver
from ai.ingredient_intelligence.normalization import normalize_ingredient_text
from ai.ingredient_intelligence.nova_classifier import classify_nova_from_ingredients
from ai.ingredient_intelligence.parser import parse_ingredient_list
from ai.ingredient_intelligence.resolver import IngredientResolver
from ai.ingredient_intelligence.service import IngredientIntelligenceService
from ai.ingredient_intelligence.signals import detect_hidden_sugars_from_taxonomy
from ai.ingredient_intelligence.taxonomy import (
    load_runtime_bundle,
)

INGREDIENTS, ADDITIVES, ALLERGENS, NOVA = load_runtime_bundle(
    "data/runtime/r4-taxonomies-v0.1.0.json.gz"
)


def test_normalize_ingredient_text() -> None:
    result = normalize_ingredient_text(
        "Ingredients:  Whole grain oats (55%),   sugar, almonds (8%), palm oil "
    )

    assert result == "Whole grain oats (55%), sugar, almonds (8%), palm oil"


def test_parse_flat_ingredient_list() -> None:
    result = parse_ingredient_list(
        "Ingredients: Whole grain oats (55%), sugar, almonds (8%), palm oil"
    )

    assert len(result.ingredients) == 4

    assert result.ingredients[0].normalized_text == "whole grain oats"
    assert result.ingredients[0].percentage == 55.0
    assert result.ingredients[0].position == 1

    assert result.ingredients[1].normalized_text == "sugar"
    assert result.ingredients[1].percentage is None

    assert result.ingredients[2].normalized_text == "almonds"
    assert result.ingredients[2].percentage == 8.0

    assert result.ingredients[3].normalized_text == "palm oil"
    assert result.ingredients[3].percentage is None

    assert result.warnings == []


def test_empty_ingredient_text_is_safe() -> None:
    result = parse_ingredient_list("")

    assert result.ingredients == []
    assert result.cleaned_text == ""
    assert result.warnings == ["No ingredient text was available for parsing."]


def test_commas_inside_parentheses_are_not_split() -> None:
    result = parse_ingredient_list("Ingredients: chocolate (sugar, cocoa butter, cocoa mass), milk")

    assert [item.normalized_text for item in result.ingredients] == [
        "chocolate",
        "sugar",
        "cocoa butter",
        "cocoa mass",
        "milk",
    ]
    assert [item.depth for item in result.ingredients] == [0, 1, 1, 1, 0]


def test_parser_bounds_adversarial_nesting() -> None:
    nested = "layer(" * 2_000 + "sugar,salt" + ")" * 2_000
    result = parse_ingredient_list(f"Ingredients: {nested}")
    assert len(result.ingredients) <= 512
    assert max((item.depth for item in result.ingredients), default=0) <= 16
    assert any("safe parsing limits" in warning for warning in result.warnings)


def test_exact_taxonomy_resolution() -> None:
    entries = INGREDIENTS
    resolver = IngredientResolver(entries)

    parsed = parse_ingredient_list("Ingredients: caramel syrup, definitely not an ingredient")

    resolved = resolver.resolve_many(parsed.ingredients)

    assert len(resolved) == 2

    assert resolved[0].taxonomy.matched is True
    assert resolved[0].taxonomy.match_method == "EXACT"
    assert resolved[0].taxonomy.taxonomy_id == "off:ingredient:caramel-syrup"
    assert resolved[0].taxonomy.canonical_name == "caramel syrup"

    assert resolved[1].taxonomy.matched is False
    assert resolved[1].taxonomy.match_method == "NONE"
    assert resolved[1].taxonomy.taxonomy_id is None


def test_taxonomy_resolution_preserves_order() -> None:
    entries = INGREDIENTS
    resolver = IngredientResolver(entries)

    parsed = parse_ingredient_list("Ingredients: unknown first, caramel syrup, unknown third")

    resolved = resolver.resolve_many(parsed.ingredients)

    assert [item.ingredient.position for item in resolved] == [1, 2, 3]
    assert resolved[1].taxonomy.matched is True


def test_additive_resolution_by_code_and_synonym() -> None:
    entries = ADDITIVES
    resolver = AdditiveResolver(entries)

    parsed = parse_ingredient_list("Ingredients: E100, curcumin, sugar")

    resolved = resolver.resolve_many(parsed.ingredients)

    assert len(resolved) == 3

    assert resolved[0].additive.matched is True
    assert resolved[0].additive.taxonomy_id == "off:additive:e100"
    assert resolved[0].additive.external_code == "E100"
    assert resolved[0].additive.functional_category == "colour"

    assert resolved[1].additive.matched is True
    assert resolved[1].additive.taxonomy_id == "off:additive:e100"

    assert resolved[2].additive.matched is False
    assert resolved[2].additive.match_method == "NONE"


def test_additive_resolution_preserves_order() -> None:
    entries = ADDITIVES
    resolver = AdditiveResolver(entries)

    parsed = parse_ingredient_list("Ingredients: sugar, E100, unknown additive")

    resolved = resolver.resolve_many(parsed.ingredients)

    assert [item.ingredient.position for item in resolved] == [1, 2, 3]
    assert resolved[1].additive.matched is True


def test_allergen_resolution_by_name_and_synonym() -> None:
    entries = ALLERGENS
    resolver = AllergenResolver(entries)

    parsed = parse_ingredient_list("Ingredients: wheat flour, shrimp, sugar")

    resolved = resolver.resolve_many(parsed.ingredients)

    assert len(resolved) == 3

    assert resolved[0].allergen.matched is True
    assert resolved[0].allergen.taxonomy_id == "off:allergen:gluten"
    assert resolved[0].allergen.canonical_name == "gluten"

    assert resolved[1].allergen.matched is True
    assert resolved[1].allergen.taxonomy_id == "off:allergen:crustaceans"
    assert resolved[1].allergen.canonical_name == "crustaceans"

    assert resolved[2].allergen.matched is False
    assert resolved[2].allergen.match_method == "NONE"


def test_allergen_none_record_is_not_loaded() -> None:
    entries = ALLERGENS

    assert all(entry.taxonomy_id != "off:allergen:none" for entry in entries)


def test_explicit_package_allergen_statement_has_priority_and_provenance() -> None:
    service = IngredientIntelligenceService(INGREDIENTS, ADDITIVES, ALLERGENS, NOVA)
    result = service.analyze(
        IngredientExtraction(
            raw_text="Pasteurized Cow Milk",
            allergen_text="Contains: Milk",
            confidence=0.9,
            allergen_confidence=0.95,
        )
    )

    milk = next(item for item in result.allergens if item.allergen.matched)
    assert milk.allergen.canonical_name == "milk"
    assert milk.allergen.match_method == "EXPLICIT_STATEMENT"
    assert milk.allergen.evidence_source == "PACKAGE_ALLERGEN_STATEMENT_OCR"
    assert milk.allergen.evidence_text == "Contains: Milk"


def test_nova_4_from_explicit_processing_marker() -> None:
    nova_entries = NOVA

    parsed = parse_ingredient_list("Ingredients: oats, maltodextrin, sugar")

    result = classify_nova_from_ingredients(
        parsed.ingredients,
        nova_entries,
    )

    assert result.group_number == 4
    assert result.taxonomy_id == ("off:nova_group:4-ultra-processed-food-and-drink-products")
    assert result.classification_method == "RULE_EVIDENCE"
    assert len(result.evidence) == 1
    assert result.evidence[0].evidence_value == "maltodextrin"


def test_nova_is_unknown_without_sufficient_evidence() -> None:
    nova_entries = NOVA

    parsed = parse_ingredient_list("Ingredients: oats, almonds")

    result = classify_nova_from_ingredients(
        parsed.ingredients,
        nova_entries,
    )

    assert result.group_number is None
    assert result.taxonomy_id is None
    assert result.classification_method == "UNKNOWN"
    assert result.evidence == []
    assert len(result.warnings) == 1


def test_hidden_sugar_detection_from_taxonomy() -> None:
    entries = INGREDIENTS

    parsed = parse_ingredient_list("Ingredients: sucrose, maltose, molasses, almond")

    result = detect_hidden_sugars_from_taxonomy(
        parsed.ingredients,
        entries,
    )

    assert len(result.signals) == 3

    assert result.signals[0].ingredient_text == "sucrose"
    assert result.signals[0].evidence_source == "OFF_TAXONOMY"

    assert result.signals[1].ingredient_text == "maltose"
    assert result.signals[1].evidence_source == "OFF_TAXONOMY"

    assert result.signals[2].ingredient_text == "molasses"
    assert result.signals[2].evidence_source == "OFF_TAXONOMY"


def test_taxonomy_sugar_detection_excludes_non_sugar() -> None:
    entries = INGREDIENTS

    parsed = parse_ingredient_list("Ingredients: almond")

    result = detect_hidden_sugars_from_taxonomy(
        parsed.ingredients,
        entries,
    )

    assert result.signals == []
