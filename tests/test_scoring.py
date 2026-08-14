from pathlib import Path

import numpy as np
import pytest

from backend.app.core.errors import InvalidModelInputError, ModelUnavailableError
from backend.app.scoring.predictor import ARTIFACT_FEATURE_ORDER, FEATURE_ORDER, HealthScoreService


FEATURES = {
    "energy_100g": 840,
    "fat_100g": 10,
    "saturated_fat_100g": 3,
    "sugars_100g": 12,
    "fiber_100g": 2,
    "proteins_100g": 5,
    "salt_100g": 0.5,
    "sodium_100g": 0.2,
}


class FakeModel:
    feature_names_in_ = np.array(ARTIFACT_FEATURE_ORDER)

    def __init__(self):
        self.frames = []

    def predict(self, frame):
        self.frames.append(frame)
        return [7.5]


def test_missing_artifact_behavior(tmp_path):
    service = HealthScoreService(tmp_path / "missing.joblib")
    assert service.readiness() == (False, "Model artifact is missing.")
    with pytest.raises(ModelUnavailableError):
        service.predict(FEATURES)


def test_complete_prediction_uses_named_expected_feature_order(tmp_path):
    model_path = tmp_path / "model.joblib"
    model_path.touch()
    model = FakeModel()
    service = HealthScoreService(model_path, loader=lambda _: model)
    assert service.predict(FEATURES) == 7.5
    assert tuple(model.frames[0].columns) == ARTIFACT_FEATURE_ORDER
    assert model.frames[0].iloc[0]["saturated-fat_100g"] == 3


def test_missing_required_feature_is_rejected_before_loading(tmp_path):
    service = HealthScoreService(tmp_path / "missing.joblib")
    incomplete = dict(FEATURES)
    incomplete.pop("fiber_100g")
    with pytest.raises(InvalidModelInputError):
        service.predict(incomplete)


def test_model_is_loaded_only_once(tmp_path):
    path = tmp_path / "model.joblib"
    path.touch()
    calls = []
    service = HealthScoreService(path, loader=lambda value: calls.append(value) or FakeModel())
    service.predict(FEATURES)
    service.predict(FEATURES)
    assert calls == [path.resolve()]


def test_incompatible_feature_schema_is_unavailable(tmp_path):
    path = tmp_path / "model.joblib"
    path.touch()
    model = FakeModel()
    model.feature_names_in_ = np.array(["wrong"])
    service = HealthScoreService(path, loader=lambda _: model)
    with pytest.raises(ModelUnavailableError):
        service.predict(FEATURES)


def test_expected_api_feature_order_is_stable():
    assert FEATURE_ORDER == tuple(FEATURES)
