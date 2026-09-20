from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import numpy as np

from backend.app.services.m5 import M5Phase1Explainer
from backend.app.xai import ShapAttributionService
from tests.test_m5_integration import make_kb, m2_result, nlp_result


class Matrix:
    def __init__(self, values):
        self.values = np.asarray(values, dtype=float)
        self.shape = self.values.shape
        self.nnz = int(np.count_nonzero(self.values))

    def toarray(self):
        return self.values.copy()


class Model:
    classes_ = np.asarray([2, 0, 1])
    estimators_ = [object(), object()]


class ContextRiskService:
    def __init__(self, *, features=None, model=None):
        self.calls = 0
        self.predict_calls = 0
        self.context = SimpleNamespace(
            model=model or Model(),
            features=features or Matrix([[0.8, 0.4, 0.0]]),
            feature_names=np.asarray(["palm oil", "sugar", "absent"]),
            classes=(model or Model()).classes_,
            ingredient_text="wheat flour, sugar, palm oil",
        )

    @staticmethod
    def risk_label(value):
        return ("LOW", "MODERATE", "HIGH")[int(value)]

    def explanation_context(self, ingredient_text):
        self.calls += 1
        assert ingredient_text == "wheat flour, msg, oats"
        return self.context

    def predict(self, ingredients):
        self.predict_calls += 1
        raise AssertionError("SHAP must not rerun ingredient-risk prediction.")


class FakeExplainer:
    expected_value = np.asarray([0.1, 0.3, 0.6])

    def __init__(self, model, *, data, feature_perturbation, model_output):
        assert isinstance(model, Model)
        assert np.array_equal(data, np.zeros((1, 3)))
        assert feature_perturbation == "interventional"
        assert model_output == "probability"

    def shap_values(self, values, *, check_additivity):
        assert check_additivity is True
        assert values.shape == (1, 3)
        # Axis order is request, TF-IDF feature, model class [HIGH, LOW, MODERATE].
        return np.asarray(
            [[[-0.05, -0.1, 0.2], [0.05, 0.0, -0.1], [0.0, 0.0, 0.0]]]
        )


FAKE_SHAP = SimpleNamespace(__version__="0.test", TreeExplainer=FakeExplainer)


def make_service(risk_service=None, **overrides):
    options = {
        "enabled": True,
        "module_loader": lambda name: FAKE_SHAP,
        "clock": lambda: 1.0,
    }
    options.update(overrides)
    return ShapAttributionService(risk_service or ContextRiskService(), **options)


def test_multiclass_alignment_sign_baseline_and_additivity():
    risk_service = ContextRiskService()
    result = make_service(risk_service).explain(m2_result())

    assert result["status"] == "available"
    assert result["method"] == "shap_tree_explainer"
    assert result["class_order"] == ["HIGH", "LOW", "MODERATE"]
    assert result["explained_class"] == "MODERATE"
    assert result["baseline"]["probability"] == 0.6
    assert result["predicted_probability"] == 0.7
    assert result["reconstructed_probability"] == 0.7
    assert result["max_additivity_residual"] < 1e-12
    assert result["total_feature_contribution"] == 0.1
    assert result["features"] == [
        {
            "tfidf_token": "palm oil",
            "token_kind": "ngram",
            "tfidf_value": 0.8,
            "contribution": 0.2,
            "direction": "increases_class_probability",
        },
        {
            "tfidf_token": "sugar",
            "token_kind": "unigram",
            "tfidf_value": 0.4,
            "contribution": -0.1,
            "direction": "decreases_class_probability",
        },
    ]
    assert risk_service.predict_calls == 0


def test_repeated_inputs_are_deterministic_and_reuse_the_explainer():
    risk_service = ContextRiskService()
    calls = []

    class CountingExplainer(FakeExplainer):
        def __init__(self, *args, **kwargs):
            calls.append("created")
            super().__init__(*args, **kwargs)

    module = SimpleNamespace(__version__="0.test", TreeExplainer=CountingExplainer)
    service = make_service(risk_service, module_loader=lambda name: module)

    first = service.explain(m2_result())
    second = service.explain(m2_result())

    assert first == second
    assert calls == ["created"]
    assert risk_service.calls == 2
    assert risk_service.predict_calls == 0


def test_disabled_shap_does_not_load_dependencies_or_touch_model():
    risk_service = ContextRiskService()
    service = ShapAttributionService(
        risk_service,
        enabled=False,
        module_loader=lambda name: (_ for _ in ()).throw(AssertionError()),
    )

    result = service.explain(m2_result())

    assert result["status"] == "disabled"
    assert result["requested"] is False
    assert risk_service.calls == 0


def test_missing_or_invalid_m2_input_fails_before_loading_shap():
    risk_service = ContextRiskService()
    service = make_service(
        risk_service,
        module_loader=lambda name: (_ for _ in ()).throw(AssertionError()),
    )
    invalid = m2_result()
    invalid["ingredient_risk"]["ingredient_text"] = ""

    result = service.explain(invalid)

    assert result["status"] == "unavailable"
    assert result["reason"] == "m2_risk_result_unavailable"
    assert risk_service.calls == 0


def test_missing_dependency_and_failed_explainer_are_explicit():
    def missing(name):
        raise ImportError("not installed")

    missing_result = make_service(module_loader=missing).explain(m2_result())
    failed_module = SimpleNamespace(
        __version__="0.test",
        TreeExplainer=lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("boom")
        ),
    )
    failed_result = make_service(
        module_loader=lambda name: failed_module
    ).explain(m2_result())

    assert missing_result["reason"] == "dependency_unavailable"
    assert failed_result["reason"] == "explanation_failure"
    assert not missing_result["available"]
    assert not failed_result["available"]


def test_shape_and_additivity_failures_never_return_attributions():
    class BadShapeExplainer(FakeExplainer):
        def shap_values(self, values, *, check_additivity):
            return np.zeros((1, 3, 2))

    bad_shape = SimpleNamespace(
        __version__="0.test", TreeExplainer=BadShapeExplainer
    )
    shape_result = make_service(
        module_loader=lambda name: bad_shape
    ).explain(m2_result())
    mismatched = m2_result()
    mismatched["ingredient_risk"]["probabilities"]["MODERATE"] = 69.0
    additivity_result = make_service().explain(mismatched)

    assert shape_result["reason"] == "output_shape_mismatch"
    assert additivity_result["reason"] == "additivity_mismatch"
    assert "features" not in shape_result
    assert "features" not in additivity_result


def test_feature_nonzero_tree_memory_and_runtime_limits_are_enforced():
    feature_result = make_service(max_features=2).explain(m2_result())
    nonzero_result = make_service(max_nonzero_features=1).explain(m2_result())
    tree_result = make_service(max_trees=1).explain(m2_result())

    ticks = iter([1.0, 1.5])
    runtime_result = make_service(
        max_runtime_ms=100,
        clock=lambda: next(ticks),
    ).explain(m2_result())

    assert feature_result["reason"] == "feature_limit"
    assert nonzero_result["reason"] == "nonzero_feature_limit"
    assert tree_result["reason"] == "tree_limit"
    assert runtime_result["reason"] == "runtime_limit"
    assert "features" not in runtime_result


def test_concurrency_limit_returns_without_touching_the_model():
    risk_service = ContextRiskService()
    service = make_service(risk_service)
    assert service._capacity.acquire(blocking=False)
    try:
        result = service.explain(m2_result())
    finally:
        service._capacity.release()

    assert result["reason"] == "concurrency_limit"
    assert risk_service.calls == 0


def test_m5_preserves_m2_result_and_phase1_when_shap_is_available(tmp_path):
    source = m2_result()
    before = deepcopy(source)
    risk_service = ContextRiskService()
    explainer = M5Phase1Explainer(make_kb(tmp_path), make_service(risk_service))

    result = explainer.explain(nlp_result(), source)

    assert source == before
    assert result["status"] == "available"
    assert result["model_attribution"]["available"] is True
    assert result["knowledge_base"]["status"] == "available"
    assert result["nutrition"]["health_score"] == source["health_score"]
    assert result["ingredient_risk"]["probabilities"] == source[
        "ingredient_risk"
    ]["probabilities"]
    assert result["methodology"]["dynamic_shap"] == (
        "shap_tree_explainer_interventional_probability"
    )
    assert risk_service.predict_calls == 0


def test_requested_but_unavailable_shap_keeps_phase1_as_partial(tmp_path):
    service = make_service(
        module_loader=lambda name: (_ for _ in ()).throw(ImportError())
    )
    result = M5Phase1Explainer(make_kb(tmp_path), service).explain(
        nlp_result(), m2_result()
    )

    assert result["status"] == "partial"
    assert result["knowledge_base"]["status"] == "available"
    assert result["recommendations"]["items"]
    assert result["model_attribution"]["reason"] == "dependency_unavailable"
    assert result["model_attribution"]["detail"] in result["warnings"]
