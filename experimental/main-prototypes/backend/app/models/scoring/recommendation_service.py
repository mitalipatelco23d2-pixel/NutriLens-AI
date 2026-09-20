"""
NutriLens AI - Personalized Recommendation Service

Generates realistic, explainable food recommendations using:

1. Nutrition information
2. Allergens
3. Food additives
4. Knowledge Base findings
5. Health Score
6. ML Risk Level
7. User's health goal

IMPORTANT:
These are general food-label recommendations.
They are NOT medical advice or a clinical diagnosis.
"""


# ==========================================================
# SUPPORTED USER GOALS
# ==========================================================

SUPPORTED_GOALS = {
    "general_health",
    "weight_management",
    "low_sugar",
    "low_sodium",
    "heart_health",
    "allergen_avoidance"
}


# ==========================================================
# HELPER FUNCTIONS
# ==========================================================

def safe_float(value):
    """
    Safely convert a value to float.

    Returns None when the value is missing or invalid.
    """

    if value is None:
        return None

    try:
        return float(value)

    except (
        ValueError,
        TypeError
    ):
        return None


def safe_int(value):
    """
    Safely convert a value to integer.
    """

    if value is None:
        return 0

    try:
        return int(value)

    except (
        ValueError,
        TypeError
    ):
        return 0


def normalize_goal(goal):
    """
    Normalize the user goal.
    """

    if not goal:
        return "general_health"

    goal = str(
        goal
    ).lower().strip()

    aliases = {

        "general": "general_health",

        "healthy": "general_health",

        "health": "general_health",

        "weight loss": "weight_management",

        "weight": "weight_management",

        "low sugar": "low_sugar",

        "sugar": "low_sugar",

        "low sodium": "low_sodium",

        "sodium": "low_sodium",

        "heart": "heart_health",

        "heart health": "heart_health",

        "allergy": "allergen_avoidance",

        "allergies": "allergen_avoidance",

        "allergen": "allergen_avoidance"
    }

    goal = aliases.get(
        goal,
        goal
    )

    if goal not in SUPPORTED_GOALS:

        return "general_health"

    return goal


def add_recommendation(
    recommendations,
    category,
    priority,
    message,
    reason,
    action
):
    """
    Add a structured recommendation.
    """

    recommendations.append({

        "category": category,

        "priority": priority,

        "message": message,

        "reason": reason,

        "action": action
    })


# ==========================================================
# MAIN FUNCTION
# ==========================================================

def generate_recommendations(
    nutrition=None,
    allergens=None,
    additives=None,
    kb_summary=None,
    health_score=None,
    risk_level=None,
    user_goal="general_health"
):
    """
    Generate personalized recommendations.

    Parameters
    ----------
    nutrition : dict
        Extracted nutrition information.

    allergens : list
        Detected allergens.

    additives : list
        Detected additives / INS numbers.

    kb_summary : dict
        Knowledge Base analysis summary.

    health_score : float
        NutriLens Health Score from 0-100.

    risk_level : str
        ML predicted risk level.

    user_goal : str
        User's selected health goal.

    Returns
    -------
    dict
        Frontend-ready recommendation result.
    """

    # ======================================================
    # DEFAULT VALUES
    # ======================================================

    nutrition = nutrition or {}

    allergens = allergens or []

    additives = additives or []

    kb_summary = kb_summary or {}

    goal = normalize_goal(
        user_goal
    )

    risk_level = (
        str(
            risk_level
        ).upper().strip()
        if risk_level
        else "UNKNOWN"
    )


    recommendations = []

    positive_points = []

    allergen_alerts = []


    # ======================================================
    # EXTRACT NUTRITION
    # ======================================================

    sugar = safe_float(
        nutrition.get("sugar_g")
    )

    saturated_fat = safe_float(
        nutrition.get(
            "saturated_fat_g"
        )
    )

    trans_fat = safe_float(
        nutrition.get(
            "trans_fat_g"
        )
    )

    sodium = safe_float(
        nutrition.get(
            "sodium_mg"
        )
    )

    calories = safe_float(
        nutrition.get(
            "energy_kcal"
        )
    )

    protein = safe_float(
        nutrition.get(
            "protein_g"
        )
    )

    fiber = safe_float(
        nutrition.get(
            "fiber_g"
        )
    )


    # ======================================================
    # KNOWLEDGE BASE COUNTS
    # ======================================================

    moderate_count = safe_int(
        kb_summary.get(
            "moderate_concern_count"
        )
    )

    context_count = safe_int(
        kb_summary.get(
            "context_dependent_count"
        )
    )

    long_term_count = safe_int(
        kb_summary.get(
            "long_term_risk_count"
        )
    )

    matched_count = safe_int(
        kb_summary.get(
            "matched_ingredients"
        )
    )


    # ======================================================
    # 1. SUGAR ANALYSIS
    # ======================================================

    if sugar is not None:

        if sugar >= 22.5:

            if goal == "low_sugar":

                add_recommendation(

                    recommendations,

                    "Sugar",

                    "HIGH",

                    f"This product contains "
                    f"{sugar:g} g of sugar per "
                    f"{nutrition.get('basis', 'serving')}.",

                    "The sugar level is relatively high "
                    "for a single serving.",

                    "Prefer a similar product with "
                    "lower sugar content."
                )

            else:

                add_recommendation(

                    recommendations,

                    "Sugar",

                    "HIGH",

                    f"High sugar content detected "
                    f"({sugar:g} g).",

                    "Frequent consumption of "
                    "high-sugar foods can increase "
                    "overall added/free sugar intake.",

                    "Compare similar products and "
                    "choose one with less sugar."
                )


        elif sugar >= 5:

            add_recommendation(

                recommendations,

                "Sugar",

                "MEDIUM",

                f"Moderate sugar content detected "
                f"({sugar:g} g).",

                "The product contributes a noticeable "
                "amount of sugar per serving.",

                "Check serving size and compare "
                "the sugar content with alternatives."
            )


        else:

            positive_points.append(
                f"Sugar content is relatively low "
                f"({sugar:g} g)."
            )


    # ======================================================
    # 2. SATURATED FAT
    # ======================================================

    if saturated_fat is not None:

        if saturated_fat >= 5:

            priority = "HIGH"

            if goal == "heart_health":

                message = (
                    f"High saturated fat detected "
                    f"({saturated_fat:g} g)."
                )

                action = (
                    "For a heart-conscious choice, "
                    "compare with products containing "
                    "less saturated fat."
                )

            else:

                message = (
                    f"High saturated fat detected "
                    f"({saturated_fat:g} g)."
                )

                action = (
                    "Consider a similar product "
                    "with lower saturated fat."
                )


            add_recommendation(

                recommendations,

                "Saturated Fat",

                priority,

                message,

                "High saturated-fat intake can "
                "increase the amount of saturated "
                "fat in the overall diet.",

                action
            )


        elif saturated_fat >= 1.5:

            add_recommendation(

                recommendations,

                "Saturated Fat",

                "MEDIUM",

                f"Moderate saturated fat detected "
                f"({saturated_fat:g} g).",

                "This product contributes a "
                "moderate amount of saturated fat.",

                "Compare similar products "
                "before choosing."
            )


        else:

            positive_points.append(
                "Saturated fat content is relatively low."
            )


    # ======================================================
    # 3. TRANS FAT
    # ======================================================

    if trans_fat is not None:

        if trans_fat > 0:

            add_recommendation(

                recommendations,

                "Trans Fat",

                "HIGH",

                f"Trans fat detected "
                f"({trans_fat:g} g).",

                "The label reports a non-zero "
                "trans-fat value.",

                "Prefer products reporting "
                "zero trans fat where possible."
            )

        else:

            positive_points.append(
                "No trans fat was detected "
                "in the extracted nutrition data."
            )


    # ======================================================
    # 4. SODIUM
    # ======================================================

    if sodium is not None:

        if sodium >= 600:

            add_recommendation(

                recommendations,

                "Sodium",

                "HIGH",

                f"High sodium detected "
                f"({sodium:g} mg).",

                "This product contributes a "
                "substantial amount of sodium "
                "per serving.",

                "Compare with a lower-sodium "
                "alternative."
            )


        elif sodium >= 300:

            priority = (
                "HIGH"
                if goal == "low_sodium"
                else "MEDIUM"
            )

            add_recommendation(

                recommendations,

                "Sodium",

                priority,

                f"Moderate sodium detected "
                f"({sodium:g} mg).",

                "The product contributes a "
                "noticeable amount of sodium.",

                "Compare sodium levels across "
                "similar products."
            )


        else:

            positive_points.append(
                f"Sodium content is relatively low "
                f"({sodium:g} mg)."
            )


    # ======================================================
    # 5. CALORIES
    # ======================================================

    if calories is not None:

        if goal == "weight_management":

            if calories >= 400:

                add_recommendation(

                    recommendations,

                    "Energy",

                    "MEDIUM",

                    f"This serving provides "
                    f"{calories:g} kcal.",

                    "The serving provides a "
                    "relatively substantial amount "
                    "of energy.",

                    "Check the serving size and "
                    "compare calorie content with "
                    "similar products."
                )


    # ======================================================
    # 6. PROTEIN
    # ======================================================

    if protein is not None:

        if protein >= 5:

            positive_points.append(
                f"The product provides "
                f"{protein:g} g of protein per "
                f"{nutrition.get('basis', 'serving')}."
            )


    # ======================================================
    # 7. FIBER
    # ======================================================

    if fiber is not None:

        if fiber >= 3:

            positive_points.append(
                f"The product provides "
                f"{fiber:g} g of dietary fiber."
            )


    # ======================================================
    # 8. ALLERGEN ANALYSIS
    # ======================================================

    if allergens:

        for allergen in allergens:

            allergen_name = str(
                allergen
            ).strip()

            if not allergen_name:
                continue

            allergen_alerts.append({

                "allergen":
                    allergen_name,

                "severity":
                    "HIGH",

                "message":
                    f"{allergen_name} was detected "
                    "in the product."
            })


        allergen_text = ", ".join(
            str(a)
            for a in allergens
        )


        if goal == "allergen_avoidance":

            add_recommendation(

                recommendations,

                "Allergen",

                "HIGH",

                f"Potential allergen(s) detected: "
                f"{allergen_text}.",

                "The ingredient analysis identified "
                "one or more potential allergens.",

                "Do not rely only on automated "
                "analysis. Check the package's "
                "official allergen declaration."
            )

        else:

            add_recommendation(

                recommendations,

                "Allergen",

                "HIGH",

                f"Potential allergen(s) detected: "
                f"{allergen_text}.",

                "The product contains ingredients "
                "that may be relevant to people "
                "with food allergies.",

                "Check the package allergen statement "
                "before consuming if you need to "
                "avoid these allergens."
            )


    # ======================================================
    # 9. ADDITIVES
    # ======================================================

    if additives:

        additive_count = len(
            additives
        )

        if additive_count >= 5:

            priority = "MEDIUM"

        else:

            priority = "LOW"


        add_recommendation(

            recommendations,

            "Additives",

            priority,

            f"{additive_count} food additive(s) "
            "were detected.",

            "Several additive/INS codes were "
            "identified from the ingredient text.",

            "Review the additive names and "
            "compare similar products if you "
            "prefer simpler ingredient lists."
        )

    else:

        positive_points.append(
            "No food additives were identified "
            "by the current ingredient parser."
        )


    # ======================================================
    # 10. KNOWLEDGE BASE CONCERNS
    # ======================================================

    if moderate_count > 0:

        priority = (
            "HIGH"
            if moderate_count >= 4
            else "MEDIUM"
        )


        add_recommendation(

            recommendations,

            "Knowledge Base",

            priority,

            f"{moderate_count} ingredient(s) "
            "have moderate concern in the "
            "NutriLens knowledge base.",

            "These ingredients were matched "
            "with entries requiring additional "
            "attention or context.",

            "Open the ingredient details and "
            "compare alternatives where appropriate."
        )


    if context_count > 0:

        add_recommendation(

            recommendations,

            "Ingredient Context",

            "LOW",

            f"{context_count} ingredient(s) have "
            "context-dependent concerns.",

            "The significance of these ingredients "
            "can depend on amount, usage and "
            "individual circumstances.",

            "Review the ingredient information "
            "rather than treating it as an automatic "
            "health hazard."
        )


    if long_term_count > 0:

        add_recommendation(

            recommendations,

            "Long-Term Information",

            "LOW",

            f"{long_term_count} ingredient(s) have "
            "long-term-risk information in the "
            "knowledge base.",

            "The knowledge base contains long-term "
            "risk information for these ingredients.",

            "Use this information as a reason to "
            "review the ingredient rather than as "
            "a prediction of disease."
        )


    # ======================================================
    # 11. ML RISK LEVEL
    # ======================================================

    if risk_level == "HIGH":

        add_recommendation(

            recommendations,

            "ML Risk",

            "HIGH",

            "The ML model indicates high "
            "food-health concern.",

            "The trained model classified the "
            "ingredient profile as HIGH concern.",

            "Compare this product with alternatives "
            "and review the individual risk factors."
        )


    elif risk_level == "MODERATE":

        add_recommendation(

            recommendations,

            "ML Risk",

            "MEDIUM",

            "The ML model indicates moderate "
            "food-health concern.",

            "The trained model classified the "
            "ingredient profile as MODERATE concern.",

            "Review the nutrition, ingredients and "
            "warnings before making your choice."
        )


    elif risk_level == "LOW":

        positive_points.append(
            "The ML model classified the product "
            "as LOW food-health concern."
        )


    # ======================================================
    # 12. HEALTH SCORE
    # ======================================================

    score = safe_float(
        health_score
    )

    if score is not None:

        if score < 40:

            add_recommendation(

                recommendations,

                "Health Score",

                "HIGH",

                f"Health Score is "
                f"{score:.1f}/100.",

                "The overall score is relatively low "
                "under the NutriLens scoring system.",

                "Consider comparing the product "
                "with healthier alternatives."
            )


        elif score < 70:

            add_recommendation(

                recommendations,

                "Health Score",

                "MEDIUM",

                f"Health Score is "
                f"{score:.1f}/100.",

                "The product falls into the "
                "moderate score range.",

                "Compare similar products and "
                "review the highlighted risk factors."
            )


        else:

            positive_points.append(
                f"Health Score is "
                f"{score:.1f}/100, which is "
                "in the GOOD range."
            )


    # ======================================================
    # 13. GOAL-SPECIFIC RECOMMENDATIONS
    # ======================================================

    if goal == "low_sugar":

        if sugar is None:

            add_recommendation(

                recommendations,

                "Goal",

                "LOW",

                "Sugar information could not "
                "be reliably extracted.",

                "The available label text does not "
                "provide a usable sugar value.",

                "Check the original nutrition label "
                "before making a low-sugar choice."
            )


    elif goal == "low_sodium":

        if sodium is None:

            add_recommendation(

                recommendations,

                "Goal",

                "LOW",

                "Sodium information could not "
                "be reliably extracted.",

                "The available label text does not "
                "provide a usable sodium value.",

                "Check the original nutrition label "
                "before choosing the product."
            )


    elif goal == "weight_management":

        if calories is None:

            add_recommendation(

                recommendations,

                "Goal",

                "LOW",

                "Energy information could not "
                "be reliably extracted.",

                "Calories were not available in "
                "the extracted nutrition data.",

                "Check the serving size and energy "
                "value on the original package."
            )


    # ======================================================
    # 14. REMOVE DUPLICATE RECOMMENDATIONS
    # ======================================================

    unique_recommendations = []

    seen = set()

    for item in recommendations:

        key = (
            item["category"],
            item["message"]
        )

        if key in seen:
            continue

        seen.add(key)

        unique_recommendations.append(
            item
        )


    recommendations = (
        unique_recommendations
    )


    # ======================================================
    # 15. SORT BY PRIORITY
    # ======================================================

    priority_order = {

        "HIGH": 0,

        "MEDIUM": 1,

        "LOW": 2
    }

    recommendations.sort(

        key=lambda item:
        priority_order.get(
            item["priority"],
            3
        )
    )


    # ======================================================
    # 16. OVERALL MESSAGE
    # ======================================================

    high_count = sum(

        1
        for item in recommendations
        if item["priority"] == "HIGH"
    )


    medium_count = sum(

        1
        for item in recommendations
        if item["priority"] == "MEDIUM"
    )


    if high_count > 0:

        overall_message = (
            "Several important factors were "
            "identified. Review the high-priority "
            "items before choosing this product."
        )

        overall_priority = "HIGH"


    elif medium_count > 0:

        overall_message = (
            "The product has some factors worth "
            "considering. Review the highlighted "
            "nutrition and ingredient information."
        )

        overall_priority = "MEDIUM"


    else:

        overall_message = (
            "No major concerns were identified "
            "from the currently available data."
        )

        overall_priority = "LOW"


    # ======================================================
    # 17. RETURN
    # ======================================================

    return {

        "user_goal":
            goal,

        "overall_priority":
            overall_priority,

        "overall_message":
            overall_message,

        "recommendations":
            recommendations,

        "allergen_alerts":
            allergen_alerts,

        "positive_points":
            list(
                dict.fromkeys(
                    positive_points
                )
            ),

        "recommendation_count":
            len(
                recommendations
            ),

        "disclaimer":
            (
                "NutriLens AI provides general "
                "food-label guidance and does not "
                "provide medical diagnosis or "
                "individual medical advice."
            )
    }


# ==========================================================
# TEST
# ==========================================================

if __name__ == "__main__":

    test_nutrition = {

        "energy_kcal": 480,

        "protein_g": 6,

        "sugar_g": 25,

        "fat_g": 20,

        "saturated_fat_g": 10,

        "trans_fat_g": 0,

        "fiber_g": 3,

        "sodium_mg": 400,

        "basis": "per_serving",

        "serving_size_g": 50
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

        "matched_ingredients": 7,

        "moderate_concern_count": 4,

        "context_dependent_count": 2,

        "long_term_risk_count": 6
    }


    result = generate_recommendations(

        nutrition=test_nutrition,

        allergens=test_allergens,

        additives=test_additives,

        kb_summary=test_kb,

        health_score=51.6,

        risk_level="MODERATE",

        user_goal="general_health"
    )


    # ======================================================
    # DISPLAY TEST RESULT
    # ======================================================

    print("\n================================")
    print(
        "NUTRILENS AI - "
        "PERSONALIZED RECOMMENDATIONS"
    )
    print("================================")


    print("\nUSER GOAL:")

    print(
        result["user_goal"]
    )


    print("\nOVERALL PRIORITY:")

    print(
        result["overall_priority"]
    )


    print("\nOVERALL MESSAGE:")

    print(
        result["overall_message"]
    )


    print("\nRECOMMENDATIONS:")

    for index, item in enumerate(

        result["recommendations"],

        start=1

    ):

        print(
            f"\n{index}. "
            f"[{item['priority']}] "
            f"{item['category']}"
        )

        print(
            f"   {item['message']}"
        )

        print(
            f"   Reason: "
            f"{item['reason']}"
        )

        print(
            f"   Action: "
            f"{item['action']}"
        )


    print("\nALLERGEN ALERTS:")

    for alert in result[
        "allergen_alerts"
    ]:

        print(
            f"- {alert['allergen']}: "
            f"{alert['message']}"
        )


    print("\nPOSITIVE POINTS:")

    for point in result[
        "positive_points"
    ]:

        print(
            f"- {point}"
        )


    print("\nTOTAL RECOMMENDATIONS:")

    print(
        result[
            "recommendation_count"
        ]
    )


    print("\nDISCLAIMER:")

    print(
        result["disclaimer"]
    )