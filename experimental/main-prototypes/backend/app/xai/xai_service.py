"""
NutriLens AI - Explainable AI (XAI) Service

Provides human-readable explanations for the ML
health-risk prediction.

The model uses TF-IDF features and Random Forest.

IMPORTANT:
This explanation describes model-related features.
It is not a medical diagnosis.
"""

import os
import joblib
import numpy as np


# ==========================================================
# PATHS
# ==========================================================

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

HEALTH_RISK_DIR = os.path.abspath(os.path.join(
    CURRENT_DIR,
    '..',
    'models',
    'health_risk'
))

MODEL_PATH = os.path.join(
    HEALTH_RISK_DIR,
    'health_risk_model.pkl'
)

VECTORIZER_PATH = os.path.join(
    HEALTH_RISK_DIR,
    'tfidf_vectorizer.pkl'
)


# ==========================================================
# LOAD MODEL
# ==========================================================

print("Loading XAI model...")

model = joblib.load(MODEL_PATH)

vectorizer = joblib.load(
    VECTORIZER_PATH
)

print(
    "XAI model and vectorizer loaded successfully."
)


# ==========================================================
# CLASS MAPPING
# ==========================================================

# This mapping comes directly from train_final_model.py
CLASS_MAPPING = {
    0: "LOW",
    1: "MODERATE",
    2: "HIGH"
}


def convert_class_label(label):
    """
    Convert numeric model class to readable label.
    """

    try:
        numeric_label = int(label)

        if numeric_label in CLASS_MAPPING:
            return CLASS_MAPPING[numeric_label]

    except (ValueError, TypeError):
        pass

    label_string = str(
        label
    ).upper().strip()

    if label_string in [
        "LOW",
        "MODERATE",
        "HIGH"
    ]:
        return label_string

    return "UNKNOWN"


# ==========================================================
# PREDICTION
# ==========================================================

def get_prediction(ingredients_text):
    """
    Generate ML prediction and probabilities.
    """

    X = vectorizer.transform(
        [ingredients_text]
    )

    prediction = model.predict(X)[0]

    probabilities = model.predict_proba(X)[0]

    result_probabilities = {}

    for index, probability in enumerate(
        probabilities
    ):

        numeric_class = model.classes_[index]

        class_name = convert_class_label(
            numeric_class
        )

        result_probabilities[
            class_name
        ] = round(
            float(probability) * 100,
            2
        )

    return {
        "risk_level": convert_class_label(
            prediction
        ),

        "probabilities":
            result_probabilities,

        "features": X
    }


# ==========================================================
# FEATURE EXPLANATION
# ==========================================================

def explain_ingredients(
    ingredients_text,
    top_n=10
):
    """
    Find important TF-IDF features that are
    present in the ingredient text.

    Random Forest feature importance is used
    to rank the features.
    """

    X = vectorizer.transform(
        [ingredients_text]
    )

    feature_names = np.array(
        vectorizer.get_feature_names_out()
    )

    values = X.toarray()[0]

    # Features actually present
    present_indices = np.where(
        values > 0
    )[0]

    if len(present_indices) == 0:
        return []

    importances = model.feature_importances_

    explanations = []

    for index in present_indices:

        feature = feature_names[index]

        importance = float(
            importances[index]
        )

        if importance <= 0:
            continue

        explanations.append({
            "feature": feature,
            "importance": round(
                importance,
                6
            )
        })

    explanations.sort(
        key=lambda x: x["importance"],
        reverse=True
    )

    return explanations[:top_n]


# ==========================================================
# HUMAN-READABLE EXPLANATION
# ==========================================================

def generate_explanation(
    ingredients_text,
    prediction_result,
    top_n=5
):
    """
    Convert important model features into
    frontend-friendly explanations.
    """

    important_features = explain_ingredients(
        ingredients_text,
        top_n
    )

    explanation = []

    for item in important_features:

        feature = item["feature"]

        importance = item["importance"]

        if importance >= 0.015:

            impact = "HIGH"

        elif importance >= 0.007:

            impact = "MODERATE"

        else:

            impact = "LOW"

        explanation.append({
            "feature": feature,

            "importance": importance,

            "impact": impact,

            "message": (
                f"'{feature}' is an important "
                f"feature considered by the "
                f"ML model."
            )
        })

    return {
        "risk_level":
            prediction_result[
                "risk_level"
            ],

        "explanation":
            explanation
    }


# ==========================================================
# COMPLETE XAI ANALYSIS
# ==========================================================

def analyze_with_xai(
    ingredients_text,
    top_n=5
):
    """
    Complete prediction + XAI analysis.
    """

    prediction_result = get_prediction(
        ingredients_text
    )

    explanation_result = generate_explanation(
        ingredients_text,
        prediction_result,
        top_n
    )

    return {
        "risk_level":
            prediction_result[
                "risk_level"
            ],

        "probabilities":
            prediction_result[
                "probabilities"
            ],

        "explanation":
            explanation_result[
                "explanation"
            ]
    }


# ==========================================================
# TEST
# ==========================================================

if __name__ == "__main__":

    test_ingredients = (
        "wheat flour, sugar, "
        "vegetable oil, palm oil, "
        "salt, milk powder, "
        "artificial flavour"
    )

    print("\n================================")
    print("NUTRILENS AI - XAI TEST")
    print("================================")

    print("\nINPUT INGREDIENTS:")

    print(test_ingredients)

    result = analyze_with_xai(
        test_ingredients,
        top_n=10
    )

    print("\nRISK LEVEL:")

    print(
        result["risk_level"]
    )

    print("\nPROBABILITIES:")

    for risk, probability in result[
        "probabilities"
    ].items():

        print(
            f"{risk}: {probability}%"
        )

    print("\nXAI EXPLANATION:")

    for item in result[
        "explanation"
    ]:

        print(
            f"- {item['feature']} "
            f"| Importance: "
            f"{item['importance']} "
            f"| Impact: "
            f"{item['impact']}"
        )

        print(
            f"  {item['message']}"
        )