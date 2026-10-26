from scripts.oci.verify_oci_worker import _acceptance


def _accepted_result() -> dict[str, object]:
    rows = [
        {"label": label, "canonical_label": label}
        for label in (
            "energy",
            "protein",
            "carbohydrate",
            "total sugar",
            "added sugar",
            "total fat",
            "saturated fat",
            "trans fat",
            "cholesterol",
            "sodium",
            "calcium",
        )
    ]
    return {
        "status": "COMPLETED",
        "nutrition": {
            "basis": "PER_100_ML",
            "serving_size_value": "250",
            "serving_size_unit": "ml",
            "table_rows": rows,
        },
        "ingredients": {
            "raw_text": "Pasteurized Cow Milk",
            "allergen_text": "CONTAINS MILK",
        },
        "product_name_candidates": [{"value": "Low Fat Cow Milk"}],
        "brand_candidates": [{"value": "Country Delight"}],
        "regions": [
            {"region_type": "nutrition_table", "method": "CUSTOM_MODEL"},
        ],
        "models": [
            {"loaded": True, "training_status": "CUSTOM_FINE_TUNED"},
        ],
        "ocr_results": {
            "label": {"attempts": [{"engine": "PaddleOCR", "status": "SUCCESS"}]},
        },
        "date_candidates": [],
        "warnings": [],
        "images_retained": False,
    }


def test_oci_acceptance_requires_complete_truthful_fixture() -> None:
    checks = _acceptance(_accepted_result())

    assert checks and all(checks.values())


def test_oci_acceptance_rejects_contradictory_model_status_and_decimal_date() -> None:
    result = _accepted_result()
    result["warnings"] = ["YOLO_UNAVAILABLE:MODEL_NOT_CACHED"]
    result["date_candidates"] = [{"raw_text": "0.99"}]

    checks = _acceptance(result)

    assert checks["no_contradictory_model_warning"] is False
    assert checks["no_decimal_nutrient_date"] is False
