from __future__ import annotations

import logging
import math
import threading
from pathlib import Path
from typing import Any, Callable

import joblib
import pandas as pd

from ..core.config import get_settings
from ..core.errors import InvalidModelInputError, ModelInferenceError, ModelUnavailableError

logger = logging.getLogger(__name__)

MODEL_ID = "legacy_development_health_score_model"
FEATURE_MAP = {
    "energy_100g": "energy_100g",
    "fat_100g": "fat_100g",
    "saturated_fat_100g": "saturated-fat_100g",
    "sugars_100g": "sugars_100g",
    "fiber_100g": "fiber_100g",
    "proteins_100g": "proteins_100g",
    "salt_100g": "salt_100g",
    "sodium_100g": "sodium_100g",
}
FEATURE_ORDER = tuple(FEATURE_MAP)
ARTIFACT_FEATURE_ORDER = tuple(FEATURE_MAP.values())


class HealthScoreService:
    """Trusted local model adapter owned by the backend integration layer."""

    def __init__(
        self,
        model_path: Path | None = None,
        loader: Callable[[Path], Any] = joblib.load,
    ) -> None:
        self.model_path = (model_path or get_settings().model_path).resolve()
        self._loader = loader
        self._model: Any | None = None
        self._load_error: Exception | None = None
        self._lock = threading.Lock()

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        if self._load_error is not None:
            raise ModelUnavailableError() from self._load_error
        with self._lock:
            if self._model is not None:
                return self._model
            if not self.model_path.is_file():
                self._load_error = FileNotFoundError(self.model_path)
                raise ModelUnavailableError() from self._load_error
            try:
                model = self._loader(self.model_path)
                expected = tuple(getattr(model, "feature_names_in_", ARTIFACT_FEATURE_ORDER))
                if expected != ARTIFACT_FEATURE_ORDER:
                    raise ValueError("model feature schema does not match backend adapter")
                if not hasattr(model, "predict"):
                    raise TypeError("model does not expose predict()")
                self._model = model
            except Exception as exc:
                self._load_error = exc
                logger.exception("Trusted health-score model could not be loaded")
                raise ModelUnavailableError() from exc
        return self._model

    def readiness(self) -> tuple[bool, str]:
        if not self.model_path.is_file():
            return False, "Model artifact is missing."
        try:
            self._load_model()
        except ModelUnavailableError:
            return False, "Model artifact could not be loaded."
        return True, "Health-score model is loaded."

    def predict(self, features: dict[str, float]) -> float:
        missing = [name for name in FEATURE_ORDER if name not in features]
        if missing:
            raise InvalidModelInputError(f"Missing required fields: {', '.join(missing)}")
        values: dict[str, float] = {}
        for api_name, artifact_name in FEATURE_MAP.items():
            try:
                value = float(features[api_name])
            except (TypeError, ValueError) as exc:
                raise InvalidModelInputError() from exc
            if not math.isfinite(value) or value < 0:
                raise InvalidModelInputError()
            values[artifact_name] = value

        frame = pd.DataFrame([values], columns=ARTIFACT_FEATURE_ORDER)
        try:
            prediction = float(self._load_model().predict(frame)[0])
        except ModelUnavailableError:
            raise
        except Exception as exc:
            logger.exception("Health-score inference failed")
            raise ModelInferenceError() from exc
        if not math.isfinite(prediction):
            raise ModelInferenceError()
        return prediction


_default_service: HealthScoreService | None = None
_service_lock = threading.Lock()


def get_health_score_service() -> HealthScoreService:
    global _default_service
    if _default_service is None:
        with _service_lock:
            if _default_service is None:
                _default_service = HealthScoreService()
    return _default_service


def predict_health_score(features: dict[str, float]) -> float:
    """Compatibility wrapper for the original proof-of-concept API."""
    return get_health_score_service().predict(features)
