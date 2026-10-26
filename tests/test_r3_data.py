from __future__ import annotations

from pathlib import Path

import pytest

from scripts.data.r3.build_r3_evaluation_manifest import _select
from scripts.data.r3.common import safe_child, tree_digest
from scripts.data.r3.download_off_product_images import (
    ImageCandidate,
    candidate_url,
    image_candidates,
    off_product_folder,
    selected_role,
)
from scripts.data.r3.off_embedded import normalized_yxyx_to_pixels


def test_off_normalized_boxes_use_documented_yxyx_order() -> None:
    box = normalized_yxyx_to_pixels([0.1, 0.2, 0.6, 0.8], width=100, height=200)
    assert box.x == pytest.approx(20)
    assert box.y == pytest.approx(20)
    assert box.width == pytest.approx(60)
    assert box.height == pytest.approx(100)


def test_off_normalized_boxes_clamp_only_floating_point_boundary_noise() -> None:
    box = normalized_yxyx_to_pixels([0.1, -3e-16, 1.0, 0.8], width=100, height=200)
    assert box.x == 0
    with pytest.raises(ValueError, match="invalid normalized"):
        normalized_yxyx_to_pixels([0.1, -0.01, 1.0, 0.8], width=100, height=200)


def test_off_image_roles_come_only_from_source_keys() -> None:
    assert selected_role("front_en") == "front"
    assert selected_role("ingredients_fr") == "ingredients"
    assert selected_role("nutrition") == "nutrition"
    assert selected_role("barcode_en") is None


def test_off_product_candidates_preserve_selected_and_unselected_provenance() -> None:
    row = {
        "code": "3168930010883",
        "brands": "Example",
        "product_name": [{"lang": "en", "text": "Example Food"}],
        "images": [
            {"key": "1", "imgid": None, "rev": None},
            {"key": "2", "imgid": None, "rev": None},
            {"key": "front_en", "imgid": 1, "rev": 4},
            {"key": "ingredients_en", "imgid": 2, "rev": 6},
            {"key": "3", "imgid": None, "rev": None},
        ],
    }
    candidates = image_candidates(row)
    assert [(item.image_role, item.source_kind) for item in candidates] == [
        ("front", "SELECTED_ROLE"),
        ("ingredients", "SELECTED_ROLE"),
        ("other", "RAW_UNSELECTED"),
    ]
    assert candidates[-1].image_key == "3"


def test_off_product_candidates_cap_localized_variants_per_product() -> None:
    row = {
        "code": "3168930010883",
        "images": [
            {"key": "front_fr", "imgid": 1, "rev": 1},
            {"key": "front_en", "imgid": 2, "rev": 2},
            {"key": "front", "imgid": 3, "rev": 3},
            {"key": "nutrition_fr", "imgid": 4, "rev": 4},
            {"key": "ingredients_en", "imgid": 5, "rev": 5},
            {"key": "packaging_en", "imgid": 6, "rev": 6},
            {"key": "7", "imgid": None, "rev": None},
        ],
    }
    candidates = image_candidates(row)
    assert len(candidates) == 4
    assert [candidate.image_key for candidate in candidates] == [
        "front",
        "nutrition_fr",
        "ingredients_en",
        "7",
    ]


def test_off_product_url_uses_official_folder_and_selected_filename() -> None:
    candidate = ImageCandidate(
        barcode="3168930010883",
        image_key="nutrition_fr",
        image_role="nutrition",
        image_id="3",
        revision=15,
        product_name=None,
        brand=None,
        source_kind="SELECTED_ROLE",
    )
    assert off_product_folder(candidate.barcode) == "316/893/001/0883"
    assert candidate_url(candidate, root="https://images.example") == (
        "https://images.example/316/893/001/0883/nutrition_fr.15.full.jpg"
    )


def test_safe_child_rejects_path_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes"):
        safe_child(tmp_path, "../outside")


def test_tree_digest_is_order_independent() -> None:
    first = [
        {"path": "b", "sha256": "2"},
        {"path": "a", "sha256": "1"},
    ]
    assert tree_digest(first) == tree_digest(list(reversed(first)))


def test_evaluation_selection_prevents_product_leakage() -> None:
    rows = [
        {
            "source_dataset": "dataset",
            "image_id": f"image-{index}",
            "barcode": f"product-{index // 2}",
        }
        for index in range(8)
    ]
    used: set[str] = set()
    selected = _select(rows, 4, used_products=used)
    assert len(selected) == 4
    assert len({row["barcode"] for row in selected}) == 4
    assert used == {str(row["barcode"]) for row in selected}
