"""Trust-gated, lazy loader for the M2 ingredient-risk artifacts."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Callable

import joblib
from sklearn import __version__ as sklearn_version

from ...core.errors import (
    InvalidModelInputError,
    ModelInferenceError,
    ModelUnavailableError,
)

ArtifactLoader = Callable[[Path], Any]
RISK_LEVELS = ("LOW", "MODERATE", "HIGH")


class IngredientRiskService:
    """Load M2 pickle artifacts only after explicit SHA-256 verification."""

    def __init__(
        self,
        *,
        model_path: Path,
        vectorizer_path: Path,
        expected_model_sha256: str | None,
        expected_vectorizer_sha256: str | None,
        expected_sklearn_version: str | None = None,
        loader: ArtifactLoader = joblib.load,
    ) -> None:
        self.model_path = Path(model_path)
        self.vectorizer_path = Path(vectorizer_path)
        self.expected_model_sha256 = expected_model_sha256
        self.expected_vectorizer_sha256 = expected_vectorizer_sha256
        self.expected_sklearn_version = expected_sklearn_version
        self._loader = loader
        self._model: Any = None
        self._vectorizer: Any = None
        self._lock = threading.Lock()

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def _verify_artifact(
        cls, path: Path, expected_sha256: str | None, label: str
    ) -> None:
        if expected_sha256 is None:
            raise ModelUnavailableError(f"{label} provenance digest is not configured.")
        if not path.is_file():
            raise ModelUnavailableError(f"{label} artifact is unavailable.")
        if cls._digest(path) != expected_sha256.lower():
            raise ModelUnavailableError(
                f"{label} artifact failed its SHA-256 provenance check."
            )

    def _verify_runtime(self) -> None:
        if (
            self.expected_sklearn_version is not None
            and sklearn_version != self.expected_sklearn_version
        ):
            raise ModelUnavailableError(
                "Ingredient-risk artifacts require scikit-learn "
                f"{self.expected_sklearn_version}; runtime has {sklearn_version}."
            )

    def readiness(self) -> tuple[bool, str]:
        """Check artifact presence and trust without deserializing either file."""

        try:
            self._verify_runtime()
            self._verify_artifact(
                self.model_path, self.expected_model_sha256, "Risk model"
            )
            self._verify_artifact(
                self.vectorizer_path,
                self.expected_vectorizer_sha256,
                "Risk vectorizer",
            )
        except ModelUnavailableError as exc:
            return False, str(exc)
        return True, "Verified ingredient-risk artifacts are available."

    def _load_verified_artifacts(self) -> tuple[Any, Any]:
        if self._model is not None and self._vectorizer is not None:
            return self._model, self._vectorizer
        with self._lock:
            if self._model is None or self._vectorizer is None:
                self._verify_runtime()
                self._verify_artifact(
                    self.model_path, self.expected_model_sha256, "Risk model"
                )
                self._verify_artifact(
                    self.vectorizer_path,
                    self.expected_vectorizer_sha256,
                    "Risk vectorizer",
                )
                try:
                    model = self._loader(self.model_path)
                    vectorizer = self._loader(self.vectorizer_path)
                except Exception as exc:
                    raise ModelUnavailableError(
                        "Verified ingredient-risk artifacts could not be loaded."
                    ) from exc
                if not callable(getattr(vectorizer, "transform", None)):
                    raise ModelUnavailableError(
                        "Risk vectorizer does not expose transform()."
                    )
                if not callable(getattr(model, "predict", None)):
                    raise ModelUnavailableError("Risk model does not expose predict().")
                self._model = model
                self._vectorizer = vectorizer
        return self._model, self._vectorizer

    @staticmethod
    def _ingredient_text(ingredients: Iterable[str]) -> str:
        if isinstance(ingredients, (str, bytes)) or not isinstance(
            ingredients, Iterable
        ):
            raise InvalidModelInputError(
                "Ingredient-risk input must be a collection of ingredient strings."
            )
        normalized: list[str] = []
        for item in ingredients:
            if not isinstance(item, str):
                raise InvalidModelInputError(
                    "Every ingredient-risk input item must be a string."
                )
            normalized.append(" ".join(item.lower().strip().split()))
        return ", ".join(item for item in normalized if item)

    @staticmethod
    def _risk_label(value: Any) -> str:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            numeric = None
        if numeric in {0, 1, 2}:
            return RISK_LEVELS[numeric]
        label = str(value).upper().strip()
        if label in RISK_LEVELS:
            return label
        raise ValueError(f"Unsupported risk label: {value}")

    def predict(self, ingredients: Iterable[str]) -> dict[str, Any]:
        ingredient_text = self._ingredient_text(ingredients)
        if not ingredient_text:
            raise InvalidModelInputError(
                "Ingredient-risk prediction requires at least one ingredient."
            )

        model, vectorizer = self._load_verified_artifacts()
        try:
            features = vectorizer.transform([ingredient_text])
            predicted = self._risk_label(model.predict(features)[0])

            probabilities = {label: 0.0 for label in RISK_LEVELS}
            predict_proba = getattr(model, "predict_proba", None)
            classes = getattr(model, "classes_", None)
            if callable(predict_proba) and classes is not None:
                values = predict_proba(features)[0]
                for label, probability in zip(classes, values):
                    probabilities[self._risk_label(label)] = round(
                        float(probability) * 100.0, 2
                    )
        except Exception as exc:
            raise ModelInferenceError("Ingredient-risk inference failed.") from exc

        return {
            "risk_level": predicted,
            "probabilities": probabilities,
            "ingredient_text": ingredient_text,
            "model_version": "m2_ingredient_risk_v1",
        }
