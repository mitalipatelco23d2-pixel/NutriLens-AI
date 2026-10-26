from __future__ import annotations

import numpy as np
import pytest

from ai.food_understanding.schemas import Box
from ai.ocr.paddle_engine import PaddleOCREngine, _models_cached
from scripts.data.r3.evaluate_r3_real_pipeline import (
    detection_counts,
    timing_summary,
    token_overlap,
)


def test_detection_counts_use_distinct_greedy_matches() -> None:
    reference = [Box(x=0, y=0, width=10, height=10)]
    predictions = [
        Box(x=0, y=0, width=10, height=10),
        Box(x=1, y=1, width=9, height=9),
    ]
    true_positive, false_positive, false_negative, matched_ious = detection_counts(
        reference, predictions
    )
    assert (true_positive, false_positive, false_negative) == (1, 1, 0)
    assert matched_ious == [1.0]


def test_detection_below_threshold_is_not_a_match() -> None:
    result = detection_counts(
        [Box(x=0, y=0, width=10, height=10)],
        [Box(x=9, y=9, width=10, height=10)],
    )
    assert result[:3] == (0, 1, 1)


def test_product_reference_overlap_is_not_an_error_rate() -> None:
    result = token_overlap("Milk, sugar, cocoa", "ingredients milk cocoa")
    assert result["reference_token_recall"] == pytest.approx(2 / 3)
    assert "character_error_rate" not in result


def test_timing_summary_uses_nearest_rank_p95() -> None:
    result = timing_summary([1.0, 2.0, 3.0, 4.0])
    assert result["mean_ms"] == 2.5
    assert result["p50_ms"] == 2.5
    assert result["p95_ms"] == 4.0


def test_paddle_cache_requires_detection_and_recognition_models(tmp_path) -> None:
    official = tmp_path / "official_models"
    (official / "PP-OCRv5_mobile_det").mkdir(parents=True)
    assert _models_cached(tmp_path) is False
    (official / "PP-OCRv5_mobile_rec").mkdir()
    assert _models_cached(tmp_path) is True


def test_paddle_adapter_expands_grayscale_for_predictor() -> None:
    class FakeReader:
        def predict(self, image):
            assert image.shape == (8, 9, 3)
            return []

    engine = PaddleOCREngine()
    engine._reader = FakeReader()
    attempt = engine.recognize(np.zeros((8, 9), dtype=np.uint8), ["en"])
    assert attempt.status == "NO_TEXT"
