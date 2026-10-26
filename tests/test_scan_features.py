from types import SimpleNamespace

from ai.features.scan_features import FEATURE_NAMES, build_scan_features


def test_scan_feature_vector_is_stable_bounded_and_identifier_free() -> None:
    scan = SimpleNamespace(
        contract_version="3.0.0",
        confidence_summary=SimpleNamespace(numeric_score=1.4),
        ocr_results={"front": SimpleNamespace(text="Ingredients: oats")},
        barcode_results=[SimpleNamespace(value="123")],
        product_name_candidates=[SimpleNamespace(value="Private product")],
        scan_id="must-not-leak",
        user_id="must-not-leak",
    )
    intelligence = SimpleNamespace(
        contract_version="4.0.0",
        confidence=SimpleNamespace(resolved_ingredient_ratio=0.75),
        complexity=SimpleNamespace(
            ingredient_count=4,
            additive_count=1,
            unresolved_count=1,
            compound_ingredient_count=2,
        ),
        allergens=[SimpleNamespace(allergen=SimpleNamespace(matched=True))],
        hidden_sugars=SimpleNamespace(signals=[object(), object()]),
        sodium_sources=SimpleNamespace(signals=[]),
        oils_and_fats=SimpleNamespace(signals=[object()]),
        sweeteners=SimpleNamespace(signals=[]),
        preservatives=SimpleNamespace(signals=[object()]),
        nova=SimpleNamespace(group_number=3),
    )

    result = build_scan_features(scan, intelligence)

    assert result.ordered_names == FEATURE_NAMES
    assert len(result.ordered_values()) == len(FEATURE_NAMES)
    assert result.values["r3_confidence"] == 1
    assert result.values["hidden_sugar_signal_count"] == 2
    assert result.source_contracts == {"r3": "3.0.0", "r4": "4.0.0"}
    serialized = result.model_dump_json()
    assert "must-not-leak" not in serialized
    assert "Private product" not in serialized
    assert "Ingredients: oats" not in serialized


def test_scan_feature_vector_has_deterministic_order() -> None:
    scan = SimpleNamespace(
        contract_version="3.0.0",
        confidence_summary=SimpleNamespace(numeric_score=None),
        ocr_results={},
        barcode_results=[],
        product_name_candidates=[],
    )
    intelligence = SimpleNamespace(
        contract_version="4.0.0",
        confidence=SimpleNamespace(resolved_ingredient_ratio=0),
        complexity=SimpleNamespace(
            ingredient_count=0,
            additive_count=0,
            unresolved_count=0,
            compound_ingredient_count=0,
        ),
        allergens=[],
        hidden_sugars=SimpleNamespace(signals=[]),
        sodium_sources=SimpleNamespace(signals=[]),
        oils_and_fats=SimpleNamespace(signals=[]),
        sweeteners=SimpleNamespace(signals=[]),
        preservatives=SimpleNamespace(signals=[]),
        nova=SimpleNamespace(group_number=None),
    )
    first = build_scan_features(scan, intelligence)
    second = build_scan_features(scan, intelligence)
    assert first.ordered_values() == second.ordered_values() == (0.0,) * len(FEATURE_NAMES)
