"""
NutriLens AI - Health Score Service

Generates an application-level Food Health Score from 0-100.

IMPORTANT:
This is an application heuristic score.
It is NOT a clinical diagnosis or medically validated score.
"""

def clamp(value, minimum=0, maximum=100):
    return max(minimum, min(maximum, value))


def calculate_health_score(
    risk_prediction,
    nutrition=None,
    allergens=None,
    additives=None,
    kb_summary=None
):
    nutrition = nutrition or {}
    allergens = allergens or []
    additives = additives or []
    kb_summary = kb_summary or {}

    breakdown = {}
    reasons = []
    warnings = []

    # ==================================================
    # 1. ML RISK COMPONENT
    # ==================================================

    probabilities = risk_prediction.get("probabilities", {})

    high_prob = float(probabilities.get("HIGH", 0)) / 100
    moderate_prob = float(probabilities.get("MODERATE", 0)) / 100

    # Maximum ML penalty = 20
    ml_penalty = (
        (high_prob * 15) +
        (moderate_prob * 5)
    )

    ml_penalty = min(ml_penalty, 20)

    breakdown["ml_risk_penalty"] = round(
        ml_penalty, 2
    )

    # ML explanation
    if high_prob >= 0.50:
        reasons.append(
            "The ML model indicates a high health concern."
        )
    elif moderate_prob >= 0.50:
        reasons.append(
            "The ML model indicates a moderate health concern."
        )

    # ==================================================
    # 2. NUTRITION COMPONENT
    # ==================================================

    nutrition_penalty = 0

    # ------------------------------
    # Sugar
    # ------------------------------

    sugar = nutrition.get("sugar_g")

    if sugar is not None:

        if sugar >= 22.5:
            nutrition_penalty += 12
            reasons.append(
                f"High sugar content detected ({sugar} g)."
            )

        elif sugar >= 5:
            nutrition_penalty += 5
            reasons.append(
                f"Moderate sugar content detected ({sugar} g)."
            )

    # ------------------------------
    # Saturated Fat
    # ------------------------------

    saturated_fat = nutrition.get(
        "saturated_fat_g"
    )

    if saturated_fat is not None:

        if saturated_fat >= 5:
            nutrition_penalty += 10
            reasons.append(
                f"High saturated fat detected "
                f"({saturated_fat} g)."
            )

        elif saturated_fat >= 1.5:
            nutrition_penalty += 4

    # ------------------------------
    # Trans Fat
    # ------------------------------

    trans_fat = nutrition.get(
        "trans_fat_g"
    )

    if trans_fat is not None:

        if trans_fat > 0:
            nutrition_penalty += 10
            reasons.append(
                f"Trans fat detected ({trans_fat} g)."
            )

    # ------------------------------
    # Sodium
    # ------------------------------

    sodium = nutrition.get(
        "sodium_mg"
    )

    if sodium is not None:

        if sodium >= 600:
            nutrition_penalty += 10
            reasons.append(
                f"High sodium content detected "
                f"({sodium} mg)."
            )

        elif sodium >= 300:
            nutrition_penalty += 4

    # Maximum nutrition penalty = 35
    nutrition_penalty = min(
        nutrition_penalty,
        35
    )

    breakdown["nutrition_penalty"] = nutrition_penalty

    # ==================================================
    # 3. KNOWLEDGE BASE COMPONENT
    # ==================================================

    moderate_count = int(
        kb_summary.get(
            "moderate_concern_count",
            0
        )
    )

    context_count = int(
        kb_summary.get(
            "context_dependent_count",
            0
        )
    )

    long_term_count = int(
        kb_summary.get(
            "long_term_risk_count",
            0
        )
    )

    # Moderate concerns have stronger effect
    kb_penalty = (
        moderate_count * 2
        + context_count * 0.5
        + long_term_count * 1
    )

    # Maximum KB penalty = 15
    kb_penalty = min(
        kb_penalty,
        15
    )

    breakdown["knowledge_base_penalty"] = round(
        kb_penalty,
        2
    )

    if moderate_count > 0:
        reasons.append(
            f"{moderate_count} ingredient(s) "
            "have moderate concern in the knowledge base."
        )

    # Long-term information should be presented
    # as evidence/warning, not automatically as disease risk.
    if long_term_count > 0:
        warnings.append(
            f"{long_term_count} ingredient(s) have "
            "long-term-risk information in the knowledge base."
        )

    # ==================================================
    # 4. ADDITIVE COMPONENT
    # ==================================================

    additive_penalty = min(
        len(additives) * 1,
        5
    )

    breakdown["additive_penalty"] = additive_penalty

    if additives:
        reasons.append(
            f"{len(additives)} food additive(s) detected."
        )

    # ==================================================
    # 5. ALLERGENS
    # ==================================================

    # IMPORTANT:
    # Allergens are NOT treated as general unhealthy-food
    # penalties because they are primarily personalized risks.

    allergen_penalty = 0

    breakdown["allergen_penalty"] = allergen_penalty

    if allergens:
        warnings.append(
            "Potential allergens detected: "
            + ", ".join(allergens)
        )

    # ==================================================
    # 6. CALCULATE FINAL SCORE
    # ==================================================

    total_penalty = (
        ml_penalty
        + nutrition_penalty
        + kb_penalty
        + additive_penalty
    )

    health_score = 100 - total_penalty

    health_score = round(
        clamp(health_score),
        1
    )

    # ==================================================
    # 7. SCORE LEVEL
    # ==================================================

    if health_score >= 70:
        score_level = "GOOD"

    elif health_score >= 40:
        score_level = "MODERATE"

    else:
        score_level = "POOR"

    # ==================================================
    # RESULT
    # ==================================================

    return {
        "health_score": health_score,
        "score_level": score_level,
        "risk_level": risk_prediction.get(
            "risk_level",
            "UNKNOWN"
        ),
        "breakdown": breakdown,
        "reasons": reasons,
        "warnings": warnings,
        "total_penalty": round(
            total_penalty,
            2
        )
    }


# ======================================================
# TEST
# ======================================================

if __name__ == "__main__":

    test_prediction = {
        "risk_level": "LOW",
        "probabilities": {
            "LOW": 61.5,
            "MODERATE": 13.5,
            "HIGH": 25.0
        }
    }

    test_nutrition = {
        "energy_kcal": 480,
        "protein_g": 6,
        "sugar_g": 25,
        "fat_g": 20,
        "saturated_fat_g": 10,
        "trans_fat_g": 0,
        "fiber_g": 3,
        "sodium_mg": 400
    }

    test_allergens = [
        "wheat",
        "milk"
    ]

    test_additives = [
        "503",
        "500",
        "472E"
    ]

    test_kb = {
        "moderate_concern_count": 4,
        "context_dependent_count": 2,
        "long_term_risk_count": 6
    }

    result = calculate_health_score(
        risk_prediction=test_prediction,
        nutrition=test_nutrition,
        allergens=test_allergens,
        additives=test_additives,
        kb_summary=test_kb
    )

    print("\n================================")
    print("NUTRILENS AI - HEALTH SCORE")
    print("================================")

    print(
        f"\nHEALTH SCORE: "
        f"{result['health_score']}/100"
    )

    print(
        f"SCORE LEVEL: "
        f"{result['score_level']}"
    )

    print(
        f"RISK LEVEL: "
        f"{result['risk_level']}"
    )

    print("\nBREAKDOWN:")

    for key, value in result["breakdown"].items():
        print(f"{key}: {value}")

    print("\nREASONS:")

    for reason in result["reasons"]:
        print(f"- {reason}")

    print("\nWARNINGS:")

    for warning in result["warnings"]:
        print(f"- {warning}")