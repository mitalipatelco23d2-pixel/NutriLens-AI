"""Optional, bounded SHAP attribution for the existing M2 risk prediction."""

from __future__ import annotations

import importlib
import threading
import time
from collections.abc import Callable
from typing import Any

import numpy as np

from ..models.health_risk import IngredientRiskService


class ShapAttributionService:
    """Explain the existing M2 prediction without rerunning classification."""

    method = "shap_tree_explainer"

    def __init__(
        self,
        risk_service: IngredientRiskService,
        *,
        enabled: bool = False,
        top_features: int = 8,
        max_features: int = 3_000,
        max_nonzero_features: int = 512,
        max_trees: int = 250,
        max_runtime_ms: int = 2_000,
        additivity_tolerance: float = 1e-6,
        module_loader: Callable[[str], Any] = importlib.import_module,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.risk_service = risk_service
        self.enabled = enabled
        self.top_features = top_features
        self.max_features = max_features
        self.max_nonzero_features = max_nonzero_features
        self.max_trees = max_trees
        self.max_runtime_ms = max_runtime_ms
        self.additivity_tolerance = additivity_tolerance
        self._module_loader = module_loader
        self._clock = clock
        self._capacity = threading.BoundedSemaphore(1)
        self._explainer_lock = threading.Lock()
        self._explainer_model_id: int | None = None
        self._explainer: Any = None

    def _result(
        self,
        status: str,
        detail: str,
        *,
        requested: bool | None = None,
        reason: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "available": status == "available",
            "requested": self.enabled if requested is None else requested,
            "method": self.method,
            "detail": detail,
            "reason": reason,
            **extra,
        }

    def _get_explainer(self, shap_module: Any, model: Any, dense: Any) -> Any:
        model_id = id(model)
        if self._explainer is not None and self._explainer_model_id == model_id:
            return self._explainer
        with self._explainer_lock:
            if self._explainer is None or self._explainer_model_id != model_id:
                background = np.zeros_like(dense[:1])
                self._explainer = shap_module.TreeExplainer(
                    model,
                    data=background,
                    feature_perturbation="interventional",
                    model_output="probability",
                )
                self._explainer_model_id = model_id
        return self._explainer

    @staticmethod
    def _normalized_values(raw_values: Any, class_count: int) -> np.ndarray:
        if isinstance(raw_values, list):
            values = np.stack(
                [np.asarray(class_values, dtype=float) for class_values in raw_values],
                axis=-1,
            )
        else:
            values = np.asarray(raw_values, dtype=float)
        if values.ndim == 2 and class_count == 1:
            values = values[..., np.newaxis]
        return values

    def explain(self, health_result: dict[str, Any] | None) -> dict[str, Any]:
        if not self.enabled:
            return self._result(
                "disabled",
                "Dynamic SHAP attribution is disabled by configuration.",
                requested=False,
                reason="disabled_by_default",
            )

        health = health_result if isinstance(health_result, dict) else {}
        risk = health.get("ingredient_risk")
        risk = risk if isinstance(risk, dict) else {}
        ingredient_text = risk.get("ingredient_text")
        predicted_label = risk.get("risk_level")
        probabilities = risk.get("probabilities")
        if (
            risk.get("available") is not True
            or not isinstance(ingredient_text, str)
            or not ingredient_text.strip()
            or not isinstance(predicted_label, str)
            or not isinstance(probabilities, dict)
        ):
            return self._result(
                "unavailable",
                "The existing M2 ingredient-risk result is not explainable.",
                reason="m2_risk_result_unavailable",
            )

        if not self._capacity.acquire(blocking=False):
            return self._result(
                "unavailable",
                "SHAP capacity is currently in use; no attribution was generated.",
                reason="concurrency_limit",
            )

        started = self._clock()
        try:
            try:
                shap_module = self._module_loader("shap")
            except (ImportError, ModuleNotFoundError):
                return self._result(
                    "unavailable",
                    "The optional SHAP dependency is unavailable.",
                    reason="dependency_unavailable",
                )

            context = self.risk_service.explanation_context(ingredient_text)
            features = context.features
            if getattr(features, "shape", None) is None or features.shape[0] != 1:
                return self._result(
                    "unavailable",
                    "The transformed M2 input has an unsupported shape.",
                    reason="invalid_input_shape",
                )
            feature_count = int(features.shape[1])
            if feature_count > self.max_features:
                return self._result(
                    "unavailable",
                    "The transformed input exceeds the configured SHAP feature limit.",
                    reason="feature_limit",
                    feature_count=feature_count,
                )
            sparse_nonzero_count = getattr(features, "nnz", None)
            nonzero_count = int(
                sparse_nonzero_count
                if sparse_nonzero_count is not None
                else np.count_nonzero(features)
            )
            if nonzero_count > self.max_nonzero_features:
                return self._result(
                    "unavailable",
                    "The transformed input exceeds the configured nonzero-feature limit.",
                    reason="nonzero_feature_limit",
                    present_feature_count=nonzero_count,
                )
            tree_count = len(getattr(context.model, "estimators_", ()))
            if tree_count > self.max_trees:
                return self._result(
                    "unavailable",
                    "The model exceeds the configured SHAP tree limit.",
                    reason="tree_limit",
                    tree_count=tree_count,
                )

            dense = features.toarray() if hasattr(features, "toarray") else np.asarray(features)
            dense = np.asarray(dense, dtype=float)
            max_dense_bytes = self.max_features * np.dtype(float).itemsize
            if dense.nbytes > max_dense_bytes:
                return self._result(
                    "unavailable",
                    "The dense explanation input exceeds the configured memory limit.",
                    reason="dense_memory_limit",
                    dense_input_bytes=int(dense.nbytes),
                )

            classes = list(context.classes)
            class_labels = [self.risk_service.risk_label(value) for value in classes]
            normalized_prediction = predicted_label.upper().strip()
            if normalized_prediction not in class_labels:
                return self._result(
                    "unavailable",
                    "The M2 predicted class does not match the model class ordering.",
                    reason="class_alignment_failure",
                )
            explained_index = class_labels.index(normalized_prediction)
            if any(label not in probabilities for label in class_labels):
                return self._result(
                    "unavailable",
                    "M2 probabilities do not cover the model class ordering.",
                    reason="probability_alignment_failure",
                )

            explainer = self._get_explainer(shap_module, context.model, dense)
            raw_values = explainer.shap_values(dense, check_additivity=True)
            values = self._normalized_values(raw_values, len(classes))
            expected = np.asarray(explainer.expected_value, dtype=float).reshape(-1)
            expected_shape = (1, feature_count, len(classes))
            if values.shape != expected_shape or expected.shape != (len(classes),):
                return self._result(
                    "unavailable",
                    "SHAP returned an unsupported multiclass output shape.",
                    reason="output_shape_mismatch",
                    output_shape=list(values.shape),
                )

            reconstructed = expected + values[0].sum(axis=0)
            m2_probabilities = np.asarray(
                [float(probabilities[label]) / 100.0 for label in class_labels]
            )
            residuals = np.abs(reconstructed - m2_probabilities)
            max_residual = float(residuals.max())
            if not np.isfinite(max_residual) or max_residual > self.additivity_tolerance:
                return self._result(
                    "unavailable",
                    "SHAP attributions did not reconstruct the existing M2 probabilities.",
                    reason="additivity_mismatch",
                    max_additivity_residual=max_residual,
                )

            elapsed_ms = (self._clock() - started) * 1000.0
            if elapsed_ms > self.max_runtime_ms:
                return self._result(
                    "unavailable",
                    "SHAP computation exceeded the configured runtime limit; its output was discarded.",
                    reason="runtime_limit",
                    runtime_ms=round(elapsed_ms, 3),
                )

            class_values = values[0, :, explained_index]
            input_values = dense[0]
            present_indexes = [
                int(index)
                for index in np.flatnonzero(input_values)
                if float(class_values[index]) != 0.0
            ]
            ranked_indexes = sorted(
                present_indexes,
                key=lambda index: abs(float(class_values[index])),
                reverse=True,
            )[: self.top_features]
            feature_names = list(context.feature_names)
            displayed = []
            for index in ranked_indexes:
                contribution = float(class_values[index])
                token = str(feature_names[index])
                displayed.append(
                    {
                        "tfidf_token": token,
                        "token_kind": "ngram" if " " in token else "unigram",
                        "tfidf_value": round(float(input_values[index]), 8),
                        "contribution": round(contribution, 10),
                        "direction": (
                            "increases_class_probability"
                            if contribution > 0
                            else "decreases_class_probability"
                            if contribution < 0
                            else "neutral"
                        ),
                    }
                )

            total_contribution = float(class_values.sum())
            displayed_contribution = sum(
                feature["contribution"] for feature in displayed
            )
            return self._result(
                "available",
                "SHAP attributes the existing M2 model output; it does not establish medical causality or ingredient safety.",
                explained_class=normalized_prediction,
                output_space="probability",
                baseline={
                    "reference": "all_zero_tfidf_vector_no_vocabulary_tokens",
                    "probability": round(float(expected[explained_index]), 10),
                },
                predicted_probability=round(
                    float(m2_probabilities[explained_index]), 10
                ),
                reconstructed_probability=round(
                    float(reconstructed[explained_index]), 10
                ),
                max_additivity_residual=max_residual,
                total_feature_contribution=round(total_contribution, 10),
                displayed_feature_contribution=round(displayed_contribution, 10),
                omitted_feature_contribution=round(
                    total_contribution - displayed_contribution, 10
                ),
                features=displayed,
                class_order=class_labels,
                feature_count=feature_count,
                present_feature_count=nonzero_count,
                tree_count=tree_count,
                dense_input_bytes=int(dense.nbytes),
                runtime_ms=round(elapsed_ms, 3),
                shap_version=str(getattr(shap_module, "__version__", "unknown")),
            )
        except Exception:
            return self._result(
                "unavailable",
                "Dynamic SHAP attribution failed; no attribution was generated.",
                reason="explanation_failure",
            )
        finally:
            self._capacity.release()
