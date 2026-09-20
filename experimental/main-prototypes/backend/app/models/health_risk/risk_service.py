import os
import joblib


# ============================================
# PATH CONFIGURATION
# ============================================

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

MODEL_PATH = os.path.join(
    CURRENT_DIR,
    "health_risk_model.pkl"
)

VECTORIZER_PATH = os.path.join(
    CURRENT_DIR,
    "tfidf_vectorizer.pkl"
)


# ============================================
# LOAD MODEL
# ============================================

print("Loading Health Risk Model...")
model = joblib.load(MODEL_PATH)

print("Loading TF-IDF Vectorizer...")
vectorizer = joblib.load(VECTORIZER_PATH)

print("Model and vectorizer loaded successfully.")


# ============================================
# CONVERT MODEL LABEL
# ============================================

def convert_risk_label(label):

    """
    Convert encoded model labels into
    NutriLens AI risk levels.

    Model encoding:

        0 = LOW
        1 = MODERATE
        2 = HIGH
    """

    # Handle numeric labels
    try:

        numeric_label = int(label)

        mapping = {
            0: "LOW",
            1: "MODERATE",
            2: "HIGH"
        }

        if numeric_label in mapping:
            return mapping[numeric_label]

    except (ValueError, TypeError):

        pass

    # Handle string labels
    label_string = str(label).upper().strip()

    if label_string in [
        "LOW",
        "MODERATE",
        "HIGH"
    ]:
        return label_string

    return "UNKNOWN"

# ============================================
# PREDICT HEALTH RISK
# ============================================

def predict_health_risk(normalized_ingredients):

    """
    Predict health concern level from
    normalized ingredients.
    """

    # ----------------------------------------
    # Validate input
    # ----------------------------------------

    if not normalized_ingredients:

        return {
            "risk_level": "UNKNOWN",
            "probabilities": {},
            "message": "No ingredients available."
        }

    # ----------------------------------------
    # Clean ingredients
    # ----------------------------------------

    normalized_ingredients = [
        str(item).strip()
        for item in normalized_ingredients
        if str(item).strip()
    ]

    if not normalized_ingredients:

        return {
            "risk_level": "UNKNOWN",
            "probabilities": {},
            "message": "No valid ingredients available."
        }

    # ----------------------------------------
    # Convert ingredients into text
    # ----------------------------------------

    ingredient_text = ", ".join(
        normalized_ingredients
    )

    # ----------------------------------------
    # TF-IDF
    # ----------------------------------------

    X = vectorizer.transform(
        [ingredient_text]
    )

    # ----------------------------------------
    # Prediction
    # ----------------------------------------

    raw_prediction = model.predict(X)[0]

    risk_level = convert_risk_label(
        raw_prediction
    )

    # ----------------------------------------
    # Probabilities
    # ----------------------------------------

    probability_array = model.predict_proba(X)[0]

    model_classes = model.classes_

    probabilities = {
        "LOW": 0.0,
        "MODERATE": 0.0,
        "HIGH": 0.0
    }

    for class_label, probability in zip(
        model_classes,
        probability_array
    ):

        readable_label = convert_risk_label(
            class_label
        )

        if readable_label in probabilities:

            probabilities[readable_label] = round(
                float(probability) * 100,
                2
            )

    # ----------------------------------------
    # Final result
    # ----------------------------------------

    return {

        "risk_level": risk_level,

        "probabilities": {
            "LOW": probabilities["LOW"],
            "MODERATE": probabilities["MODERATE"],
            "HIGH": probabilities["HIGH"]
        },

        "ingredient_text": ingredient_text
    }


# ============================================
# PREDICT FROM M1 + M2
# ============================================

def predict_from_nlp_result(nlp_result):

    """
    Takes M1 + M2 output and performs
    ML risk prediction.
    """

    normalized_ingredients = nlp_result.get(
        "normalized_ingredients",
        []
    )

    return predict_health_risk(
        normalized_ingredients
    )


# ============================================
# TEST
# ============================================

if __name__ == "__main__":

    print("\n================================")
    print("NUTRILENS AI - ML RISK PREDICTION")
    print("================================")

    print("\nMODEL CLASSES:")
    print(model.classes_)

    # Sample M1 + M2 result
    sample_nlp_result = {

        "normalized_ingredients": [
            "wheat flour",
            "sugar",
            "palm oil",
            "citric acid",
            "salt",
            "raising agents",
            "artificial flavour",
            "glucose",
            "fructose"
        ],

        "allergens": [
            "wheat",
            "milk"
        ],

        "additives": [
            "503",
            "500",
            "472E"
        ],

        "nutrition": {
            "energy_kcal": 480.0,
            "protein_g": 6.0,
            "sugar_g": 25.0,
            "fat_g": 20.0,
            "saturated_fat_g": 10.0,
            "trans_fat_g": 0.0,
            "sodium_mg": 400.0,
            "basis": "per_serving",
            "serving_size_g": 50.0
        }
    }

    # ----------------------------------------
    # Run prediction
    # ----------------------------------------

    result = predict_from_nlp_result(
        sample_nlp_result
    )

    # ----------------------------------------
    # Display result
    # ----------------------------------------

    print("\nRISK LEVEL:")
    print(result["risk_level"])

    print("\nPROBABILITIES:")

    print(
        f"LOW: {result['probabilities']['LOW']}%"
    )

    print(
        f"MODERATE: {result['probabilities']['MODERATE']}%"
    )

    print(
        f"HIGH: {result['probabilities']['HIGH']}%"
    )