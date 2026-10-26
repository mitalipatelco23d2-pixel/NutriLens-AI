"""Authenticated product APIs for profiles, diary, pantry, analytics and guidance."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from io import StringIO
from pathlib import Path
from threading import RLock
from time import time
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from ai.food_understanding.schemas import R3ScanResult
from ai.food_understanding.store import ScanNotFoundError
from backend.auth import User, current_user, user_store
from backend.custom_recipes_api import custom_recipe_store
from backend.entitlements import SpecialRole, resolve_entitlements
from backend.hydration_api import hydration_store
from backend.knowledge_api import (
    retrieve_alternative_ingredients,
    retrieve_health_effects,
    retrieve_knowledge,
)
from backend.llm_runtime import generate_assistant_answer
from backend.r3_api import get_owned_scan_result, scan_store
from backend.r4_api import get_r4_service
from backend.settings import settings
from backend.storage_runtime import postgres_store
from backend.weight_api import weight_store

router = APIRouter(prefix="/api/v1", tags=["NutriLens Product"])


class NutrientSnapshot(BaseModel):
    calories: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    protein_g: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    carbs_g: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    fat_g: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    sugar_g: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    sodium_mg: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    fiber_g: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    vitamin_a_mcg: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    vitamin_c_mg: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    vitamin_d_mcg: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    calcium_mg: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    iron_mg: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    potassium_mg: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    zinc_mg: float | None = Field(default=None, ge=0, allow_inf_nan=False)


def _sum_nutrients(snapshots: Iterable[NutrientSnapshot]) -> NutrientSnapshot:
    totals: dict[str, float | None] = dict.fromkeys(NutrientSnapshot.model_fields, 0.0)
    for snapshot in snapshots:
        for name, total in totals.items():
            value = getattr(snapshot, name)
            totals[name] = None if total is None or value is None else total + value
    return NutrientSnapshot(**totals)


def _scale_nutrients(snapshot: NutrientSnapshot, factor: float | None) -> NutrientSnapshot:
    return NutrientSnapshot(
        **{
            name: round(value * factor, 2) if value is not None and factor is not None else None
            for name, value in snapshot.model_dump().items()
        }
    )


class UserNutrientTargets(BaseModel):
    """Optional user-entered references; these are not clinical recommendations."""

    calories: float | None = Field(default=None, gt=0, le=20_000)
    protein_g: float | None = Field(default=None, gt=0, le=1_000)
    fiber_g: float | None = Field(default=None, gt=0, le=1_000)
    sodium_mg: float | None = Field(default=None, gt=0, le=100_000)
    calcium_mg: float | None = Field(default=None, gt=0, le=100_000)
    iron_mg: float | None = Field(default=None, gt=0, le=10_000)


class SelfReportedBodyContext(BaseModel):
    adult_attestation: bool = False
    consent_bmi_context: bool = False
    height_cm: float | None = Field(default=None, ge=100, le=250)
    weight_kg: float | None = Field(default=None, ge=20, le=500)

    @model_validator(mode="after")
    def validate_consent_and_measurements(self) -> SelfReportedBodyContext:
        has_height = self.height_cm is not None
        has_weight = self.weight_kg is not None
        if has_height != has_weight:
            raise ValueError("Height and weight must be supplied together.")
        if has_height and not self.consent_bmi_context:
            raise ValueError("Body measurements require BMI-context consent.")
        if self.consent_bmi_context and not self.adult_attestation:
            raise ValueError("BMI context requires adult attestation.")
        if self.consent_bmi_context and not has_height:
            raise ValueError("Consented BMI context requires height and weight.")
        return self


class HealthProfile(BaseModel):
    goal: Literal[
        "balanced",
        "maintain-weight",
        "lose-weight-gradually",
        "gain-weight-gradually",
        "improve-nutrition",
        "high-protein",
        "low-sugar",
        "low-sodium",
        "custom",
    ] = "balanced"
    custom_goal: str | None = Field(default=None, max_length=120)
    allergens: list[str] = Field(default_factory=list, max_length=40)
    dietary_preferences: list[str] = Field(default_factory=list, max_length=40)
    dietary_style: Literal[
        "Vegetarian",
        "Non-vegetarian",
        "Vegan",
        "Eggetarian",
        "Pescatarian",
        "Jain",
        "Keto",
        "No specific diet",
        "Custom",
    ] = "No specific diet"
    custom_dietary_style: str | None = Field(default=None, max_length=100)
    health_conditions: list[str] = Field(default_factory=list, max_length=30)
    intolerances: list[str] = Field(default_factory=list, max_length=30)
    food_exclusions: list[str] = Field(default_factory=list, max_length=50)
    consent_personalization: bool = False
    daily_targets: UserNutrientTargets = Field(default_factory=UserNutrientTargets)
    body_context: SelfReportedBodyContext = Field(default_factory=SelfReportedBodyContext)

    @field_validator("custom_goal", mode="before")
    @classmethod
    def normalize_custom_goal(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) and value.strip() else None

    @model_validator(mode="after")
    def validate_custom_goal(self) -> HealthProfile:
        if self.goal == "custom" and self.custom_goal is None:
            raise ValueError("A custom goal description is required for the custom goal.")
        if self.goal != "custom" and self.custom_goal is not None:
            raise ValueError("A custom goal description is only allowed for the custom goal.")
        return self


_PROFILE_PHONE_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")
_COUNTRY_REGION_PATTERN = re.compile(r"^[A-Z]{2}$")
_MINIMUM_ACCOUNT_AGE = 18


def _age_on(date_of_birth: date, today: date) -> int:
    return (
        today.year
        - date_of_birth.year
        - ((today.month, today.day) < (date_of_birth.month, date_of_birth.day))
    )


class AccountProfileRecord(BaseModel):
    """Private owner profile record. Raw phone never appears in the read response."""

    full_name: str = Field(min_length=2, max_length=100)
    date_of_birth: date | None = None
    phone_number: str | None = None
    phone_state: Literal["NOT_ADDED", "UNVERIFIED", "VERIFICATION_PENDING", "VERIFIED"] = (
        "NOT_ADDED"
    )
    country_region: str | None = None
    unit_system: Literal["METRIC", "IMPERIAL"] = "METRIC"
    research_insights_consent: bool = False
    onboarding_completed_at: datetime | None = None


class AccountProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2)] = Field(
        max_length=100
    )
    date_of_birth: date | None = None
    phone_update: Literal["KEEP", "SET", "REMOVE"] = "KEEP"
    phone_number: str | None = Field(default=None, min_length=8, max_length=16)
    country_region: str | None = Field(default=None, min_length=2, max_length=2)
    unit_system: Literal["METRIC", "IMPERIAL"] = "METRIC"
    research_insights_consent: bool = False
    complete_onboarding: bool = False
    accepted_terms: bool = False
    accepted_privacy: bool = False

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, value: date | None) -> date | None:
        if value is None:
            return None
        today = datetime.now(UTC).date()
        if value > today:
            raise ValueError("Date of birth cannot be in the future.")
        try:
            earliest = today.replace(year=today.year - 120)
        except ValueError:
            earliest = today.replace(year=today.year - 120, day=28)
        if value < earliest:
            raise ValueError("Date of birth must be within the last 120 years.")
        if _age_on(value, today) < _MINIMUM_ACCOUNT_AGE:
            raise ValueError("NutriLens X accounts currently require users to be 18 or older.")
        return value

    @field_validator("country_region")
    @classmethod
    def normalize_country_region(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().upper()
        if not _COUNTRY_REGION_PATTERN.fullmatch(normalized):
            raise ValueError("Country/region must be a two-letter code.")
        return normalized

    @model_validator(mode="after")
    def validate_phone_update(self) -> AccountProfileUpdate:
        if self.phone_update == "SET":
            normalized = (self.phone_number or "").strip()
            if not _PROFILE_PHONE_PATTERN.fullmatch(normalized):
                raise ValueError("Use an E.164 phone number with country code.")
            self.phone_number = normalized
        elif self.phone_number is not None:
            raise ValueError("phone_number is only accepted when phone_update is SET.")
        if self.complete_onboarding and self.date_of_birth is None:
            raise ValueError("Date of birth is required to complete onboarding.")
        return self


class AccountProfileResponse(BaseModel):
    full_name: str
    date_of_birth: date | None
    masked_phone_number: str | None
    phone_state: Literal["NOT_ADDED", "UNVERIFIED", "VERIFICATION_PENDING", "VERIFIED"]
    phone_verification_availability: Literal["READY", "BLOCKED_EXTERNAL_COST"]
    country_region: str | None
    unit_system: Literal["METRIC", "IMPERIAL"]
    research_insights_consent: bool
    onboarding_complete: bool
    age_eligibility: Literal["UNKNOWN", "ELIGIBLE_18_PLUS"]
    minimum_account_age: int = _MINIMUM_ACCOUNT_AGE
    legal_acceptance_complete: bool


class BmiContextResponse(BaseModel):
    state: Literal["NOT_CONFIGURED", "AVAILABLE"]
    bmi: float | None
    height_cm: float | None
    weight_kg: float | None
    method: str = "SELF_REPORTED_ADULT_BMI_FORMULA_V1"
    reference_url: str = "https://www.who.int/news-room/fact-sheets/detail/obesity-and-overweight"
    limitation: str = (
        "BMI is a weight-for-height surrogate calculated from self-reported adult measurements. "
        "NutriLens does not assign a category, diagnose health, estimate body fat, define an ideal "
        "weight or generate treatment or nutrition targets from this value."
    )


ProfileLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class HouseholdProfileInput(BaseModel):
    display_name: ProfileLabel = Field(max_length=100)
    relationship: Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)] | None = (
        None
    )
    profile: HealthProfile = Field(default_factory=HealthProfile)


class HouseholdProfile(HouseholdProfileInput):
    id: str
    created_at: datetime
    updated_at: datetime


class DiaryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    eaten_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    serving_grams: float | None = Field(default=None, gt=0, le=10_000, allow_inf_nan=False)
    nutrients: NutrientSnapshot = Field(default_factory=NutrientSnapshot)
    scan_id: str | None = None


class DiaryEntry(DiaryCreate):
    id: str
    source: Literal["MANUAL", "SCAN", "CUSTOM_RECIPE", "RECIPE"] = "MANUAL"
    recipe_id: str | None = None
    recipe_version: int | None = Field(default=None, ge=1)
    recipe_servings: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class DiaryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    eaten_at: datetime | None = None
    serving_grams: float | None = Field(default=None, gt=0, le=10_000, allow_inf_nan=False)
    nutrients: NutrientSnapshot | None = None
    scan_id: str | None = None


class PantryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    quantity: float = Field(default=1, gt=0, le=100_000)
    unit: str = Field(default="item", max_length=30)
    expires_on: date | None = None
    low_stock_threshold: float | None = Field(default=None, gt=0, le=100_000)
    item_role: Literal["INGREDIENT", "LEFTOVER"] = "INGREDIENT"


class PantryItem(PantryCreate):
    id: str


class PantryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    quantity: float | None = Field(default=None, gt=0, le=100_000)
    unit: str | None = Field(default=None, max_length=30)
    expires_on: date | None = None
    low_stock_threshold: float | None = Field(default=None, gt=0, le=100_000)
    item_role: Literal["INGREDIENT", "LEFTOVER"] | None = None


class LowStockResponse(BaseModel):
    items: list[PantryItem]
    method: str = "USER_DEFINED_PANTRY_THRESHOLD_V1"
    limitation: str = (
        "Low-stock status uses only the quantity and threshold you saved for the same unit. "
        "NutriLens does not infer household consumption or a required purchase amount."
    )


ShoppingLabel = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


class ShoppingListCreate(BaseModel):
    name: ShoppingLabel
    quantity: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    unit: str | None = None
    recipe_id: str | None = None


class ShoppingListItem(ShoppingListCreate):
    id: str
    checked: bool = False
    source: Literal["USER_ADDED", "LOW_STOCK", "RECIPE_PLAN"] = "USER_ADDED"
    pantry_item_id: str | None = None
    quantity: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    unit: str | None = None
    recipe_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("source", mode="before")
    @classmethod
    def _normalize_shopping_source(cls, value: object) -> str:
        if value is None:
            return "USER_ADDED"
        normalized = str(value).strip().upper()
        if normalized == "MANUAL":
            return "USER_ADDED"
        if normalized == "CUSTOM_RECIPE":
            return "RECIPE_PLAN"
        return normalized


class ShoppingListUpdate(BaseModel):
    name: ShoppingLabel | None = None
    checked: bool | None = None
    quantity: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    unit: str | None = None


class ShoppingListGenerationResponse(BaseModel):
    generated_count: int = Field(ge=0)
    items: list[ShoppingListItem]
    method: str = "USER_DEFINED_LOW_STOCK_TO_SHOPPING_LIST_V1"
    limitation: str = (
        "Generated entries come only from user-defined low-stock thresholds. "
        "Verify the product, unit and amount before shopping."
    )


class FavoriteFood(BaseModel):
    scan_id: str
    product_name: str | None = None
    brand: str | None = None
    saved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Notification(BaseModel):
    id: str
    kind: Literal["PANTRY_EXPIRY", "PANTRY_LOW_STOCK", "ACCOUNT", "SUBSCRIPTION"]
    title: str
    body: str
    action_href: str | None = None
    read_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GoalProgress(BaseModel):
    nutrient: str
    label: str
    unit: str
    daily_average: float | None = Field(ge=0)
    user_target: float = Field(gt=0)
    percent_of_target: float | None = Field(ge=0)


class AnalyticsSummary(BaseModel):
    period_days: int
    diary_entries: int
    totals: NutrientSnapshot
    daily_averages: NutrientSnapshot
    insights: list[str]
    goal_tracking_state: Literal["AVAILABLE", "NOT_CONFIGURED", "DISABLED_NO_CONSENT"]
    goal_progress: list[GoalProgress]
    goal_tracking_limitation: str = (
        "Progress compares logged diary averages with references entered by the user. "
        "It does not assess nutritional adequacy or provide a clinical target."
    )


class AnalyticsTrendPoint(NutrientSnapshot):
    date: date


class AnalyticsPeriodSnapshot(BaseModel):
    first_date: date
    last_date: date
    logged_days: int = Field(ge=0)
    diary_entries: int = Field(ge=0)
    daily_averages: NutrientSnapshot


class AnalyticsMetricChange(BaseModel):
    nutrient: str
    label: str
    unit: str
    direction: Literal["HIGHER", "LOWER", "UNCHANGED", "NOT_COMPARABLE"]
    absolute_change: float | None
    percent_change: float | None


class AnalyticsStory(BaseModel):
    kind: Literal["PERIOD_COVERAGE", "RECORDED_AVERAGE_CHANGE"]
    title: str
    evidence: str
    supporting_records: int = Field(ge=0)


class AnalyticsComparisonResponse(BaseModel):
    state: Literal["AVAILABLE", "INSUFFICIENT_HISTORY"]
    period_days: int
    current: AnalyticsPeriodSnapshot
    previous: AnalyticsPeriodSnapshot
    changes: list[AnalyticsMetricChange]
    stories: list[AnalyticsStory]
    method: str = "OWNER_DIARY_EQUAL_WINDOW_DESCRIPTIVE_COMPARISON_V1"
    limitation: str = (
        "This compares user-recorded diary values in adjacent equal UTC windows. Daily averages "
        "use only days with entries; selective logging, missing nutrients and different serving "
        "records can change the result. It does not assess improvement, health or causation."
    )


class ResearchAggregate(BaseModel):
    state: Literal["AVAILABLE", "INSUFFICIENT_COHORT"]
    minimum_cohort: int
    deidentified_user_count: int | None
    diary_entry_count: int | None
    nutrient_totals: NutrientSnapshot | None
    method: str = "FIXED_WINDOW_COARSE_COHORT_BAND_V3"
    limitation: str = (
        "Aggregate logged nutrition is descriptive and is not representative population evidence."
    )


class IngredientSubstitution(BaseModel):
    missing_ingredient: str
    available_alternative: str
    function: str
    limitation: str


class PreparationComplexity(BaseModel):
    band: Literal["BASIC", "MODERATE", "INVOLVED"]
    written_steps: int = Field(ge=0)
    required_ingredients: int = Field(ge=0)
    method: str = "CURATED_TEMPLATE_COUNT_BAND_V1"
    limitation: str = (
        "A structural estimate from written step and required-ingredient counts only. It does not "
        "measure time, equipment, cooking skill, accessibility or individual difficulty."
    )


class IngredientDeficit(BaseModel):
    ingredient: str
    required_quantity: float | None = None
    available_quantity: float | None = None
    missing_quantity: float | None = None
    unit: str | None = None
    status: Literal["AVAILABLE", "DEFICIT", "MISSING", "UNIT_UNCERTAIN"] = "AVAILABLE"


class RecipeRecommendation(BaseModel):
    recipe_id: str
    title: str
    required_ingredients: list[str] = Field(default_factory=list)
    available_ingredients: list[str]
    missing_required: list[str]
    optional_available: list[str]
    coverage: float = Field(ge=0, le=1)
    steps: list[str]
    source: str
    source_version: str
    method: str
    available_substitutions: list[IngredientSubstitution] = Field(default_factory=list)
    preparation_complexity: PreparationComplexity
    deficits: list[IngredientDeficit] = Field(default_factory=list)
    servings: float = 1.0
    nutrients_per_serving: NutrientSnapshot | None = None
    total_ingredients_count: int | None = None
    complete_ingredients: list[dict[str, Any]] | None = None
    nutrition_provenance: str | None = None


class TemplateRecipePlanRequest(BaseModel):
    servings: float = Field(default=1.0, gt=0, le=100)


class TemplateRecipePlanResponse(BaseModel):
    template_id: str
    servings: float
    generated_count: int
    items: list[ShoppingListItem]
    deficits: list[IngredientDeficit]
    method: str = "PANTRY_DEFICIT_TO_SHOPPING_PLAN_V1"


class PantryAttentionItem(BaseModel):
    pantry_item_id: str
    name: str
    reasons: list[Literal["USER_MARKED_LEFTOVER", "EXPIRES_TODAY", "EXPIRING_SOON"]]


class UseSoonRecipeSuggestion(BaseModel):
    recipe: RecipeRecommendation
    attention_items: list[PantryAttentionItem]


class UseSoonRecipeResponse(BaseModel):
    suggestions: list[UseSoonRecipeSuggestion]
    method: str = "USER_MARKED_LEFTOVER_AND_EXPIRY_TEMPLATE_MATCH_V1"
    limitation: str = (
        "Suggestions match saved pantry names to curated recipe templates. Check the package, "
        "storage history, allergens and food condition first; never use expired or spoiled food. "
        "NutriLens does not determine food safety or generate nutrition values."
    )


class RecipeNutritionInput(BaseModel):
    name: ProfileLabel = Field(max_length=200)
    servings: float = Field(default=1, gt=0, le=1_000)
    nutrients: NutrientSnapshot
    source_label: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
        | None
    ) = None


class RecipeNutritionComparisonRequest(BaseModel):
    candidates: list[RecipeNutritionInput] = Field(min_length=2, max_length=5)


class RecipeNutritionCandidate(RecipeNutritionInput):
    per_serving: NutrientSnapshot


class RecipeNutritionComparisonResponse(BaseModel):
    candidates: list[RecipeNutritionCandidate]
    compared_nutrients: list[str]
    method: str = "DIRECT_USER_SUPPLIED_RECIPE_NUTRIENT_COMPARISON_V1"
    limitation: str = (
        "Descriptive normalization of supplied recipe totals only. Results depend on ingredient "
        "quantities, yield, serving count and source accuracy; no recipe is ranked as healthier."
    )


class PersonalizedFinding(BaseModel):
    level: Literal["INFO", "CAUTION", "SAFETY"]
    title: str
    explanation: str
    evidence: list[str] = Field(default_factory=list)


class PersonalFitScore(BaseModel):
    score: int | None = Field(default=None, ge=0, le=100)
    category: Literal["GREAT_FIT", "GOOD_FIT", "MODERATE_FIT", "POOR_FIT", "NOT_ENOUGH_EVIDENCE"]
    label: str
    reasons: list[str] = Field(default_factory=list)
    evidence_sufficiency: Literal["SUFFICIENT", "PARTIAL", "INSUFFICIENT"] = "SUFFICIENT"


class BetterAlternative(BaseModel):
    name: str
    category: str
    why_better: str
    key_nutrition_advantage: str
    dietary_compatibility: list[str] = Field(default_factory=list)


class RecommendationResponse(BaseModel):
    scan_id: str
    findings: list[PersonalizedFinding]
    advanced: bool
    profile_used: bool
    personalization_state: Literal["ENABLED", "DISABLED_NO_CONSENT"]
    fit_score: PersonalFitScore | None = None
    better_alternatives: list[BetterAlternative] = Field(default_factory=list)
    disclaimer: str = "Wellness decision support only; not a diagnosis or medical prescription."


class ObservedSignalCounterfactual(BaseModel):
    factor_id: str
    label: str
    observed_evidence: list[str]
    hypothesis: str
    result_change: str
    method: str = "SINGLE_OBSERVED_SIGNAL_CATEGORY_ABLATION_V1"


class CounterfactualExplanationResponse(BaseModel):
    scan_id: str
    state: Literal["AVAILABLE", "NO_OBSERVED_SIGNALS"]
    factors: list[ObservedSignalCounterfactual]
    limitation: str = (
        "These are hypothetical removals of recognized label-evidence signals only. They do "
        "not predict a reformulation, taste, nutrition, safety, suitability or health outcome, "
        "and they are not advice to remove an ingredient. Other label evidence may also change."
    )


class ComparisonRequest(BaseModel):
    scan_ids: list[str] = Field(min_length=2, max_length=5)


class FoodNutrientValues(BaseModel):
    energy_kcal: float | None = None
    protein_g: float | None = None
    carbohydrate_g: float | None = None
    sugar_g: float | None = None
    added_sugar_g: float | None = None
    fat_g: float | None = None
    fiber_g: float | None = None
    sodium_mg: float | None = None


class ComparisonCandidate(BaseModel):
    scan_id: str
    product_name: str
    rank: int
    signal_burden: int = Field(ge=0)
    signal_counts: dict[str, int]
    evidence: list[str]
    limitations: list[str]
    brand_name: str | None = None
    serving_size: str | None = None
    basis: str | None = None
    nutrients_per_100: FoodNutrientValues = Field(default_factory=FoodNutrientValues)
    nutrients_per_serving: FoodNutrientValues = Field(default_factory=FoodNutrientValues)
    allergens: list[str] = Field(default_factory=list)


class ComparisonResponse(BaseModel):
    candidates: list[ComparisonCandidate]
    recommended_scan_id: str | None
    profile_used: bool
    compared_nutrients: list[str] = Field(
        default_factory=lambda: [
            "energy_kcal",
            "protein_g",
            "carbohydrate_g",
            "sugar_g",
            "added_sugar_g",
            "fat_g",
            "fiber_g",
            "sodium_mg",
        ]
    )
    method: str = "DETERMINISTIC_OBSERVED_SIGNAL_COMPARISON_V1"
    disclaimer: str = (
        "Comparison ranks observed label signals and displays nutrition, serving sizes, and "
        "allergens side-by-side. Unreported values remain missing; it is not a health score "
        "or safety guarantee."
    )


class MealComparisonRequest(BaseModel):
    entry_ids: list[str] = Field(min_length=2, max_length=5)


class MealComparisonCandidate(BaseModel):
    entry_id: str
    name: str
    eaten_at: datetime
    serving_grams: float | None = Field(gt=0, allow_inf_nan=False)
    logged_serving: NutrientSnapshot
    per_100g: NutrientSnapshot


class MealComparisonResponse(BaseModel):
    candidates: list[MealComparisonCandidate]
    compared_nutrients: list[str]
    method: str = "DIRECT_LOGGED_NUTRIENT_COMPARISON_V1"
    limitation: str = (
        "Descriptive comparison of user-recorded values only. Missing or inaccurate diary "
        "values remain missing or inaccurate; no meal is ranked as healthier."
    )


class AnalyticsDrilldownResponse(BaseModel):
    period_days: int
    selected_date: date | None
    entries: list[DiaryEntry]
    method: str = "OWNER_SCOPED_DIARY_RECORD_DRILLDOWN_V1"
    limitation: str = (
        "These are the underlying user-recorded diary entries for the selected analytics "
        "window, not independently verified intake measurements."
    )


class DietaryPatternObservation(BaseModel):
    kind: Literal["LOGGING_COVERAGE", "RECURRING_ENTRY", "MEAL_TIMING", "NUTRIENT_RANGE"]
    label: str
    evidence: str
    supporting_records: int = Field(ge=1)


class DietaryPatternResponse(BaseModel):
    period_days: int
    state: Literal["AVAILABLE", "INSUFFICIENT_HISTORY"]
    observed_days: int
    minimum_observed_days: int = 7
    observations: list[DietaryPatternObservation]
    method: str = "DESCRIPTIVE_OWNER_DIARY_PATTERN_ANALYSIS_V1"
    limitation: str = (
        "Patterns describe logged diary records in UTC and can reflect missing or selective "
        "logging. They do not classify a diet, assess adequacy or predict health outcomes."
    )


class SimilarProductCandidate(BaseModel):
    scan_id: str
    product_name: str
    similarity: float = Field(ge=0, le=1)
    compared_nutrients: list[str]
    evidence: list[str]


class SimilarProductResponse(BaseModel):
    scan_id: str
    state: Literal["AVAILABLE", "INSUFFICIENT_COMPARABLE_EVIDENCE"]
    candidates: list[SimilarProductCandidate]
    method: str = "OWNER_SCOPED_LABEL_NUTRIENT_SIMILARITY_V1"
    limitation: str = (
        "Similarity compares overlapping numeric label evidence only. It is not a health "
        "ranking, substitute recommendation, or proof of complete nutritional equivalence."
    )


class UniversalSearchItem(BaseModel):
    kind: Literal["SCAN", "INGREDIENT", "ADDITIVE", "ALLERGEN", "SUBSTITUTION"]
    id: str
    title: str
    subtitle: str
    score: float = Field(ge=0, le=1)


class UniversalSearchResponse(BaseModel):
    query: str
    items: list[UniversalSearchItem]
    method: str = "OWNER_SCAN_AND_GOVERNED_LEXICAL_SEARCH_V2"
    limitation: str = (
        "Search covers owner-scoped scan names/brands, the compact governed taxonomy and "
        "curated cooking-function substitutions. It is not a complete food catalogue, "
        "semantic health search or nutritional-equivalence claim."
    )


class AssistantRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2_000)
    scan_id: str | None = None


class AssistantCitation(BaseModel):
    evidence_id: str
    title: str
    authority: str
    url: str


class AssistantResponse(BaseModel):
    answer: str
    evidence: list[str]
    citations: list[AssistantCitation] = Field(default_factory=list)
    remaining_today: int
    generation_mode: str = "DETERMINISTIC_FALLBACK"
    method: str = "GOVERNED_LEXICAL_EVIDENCE_ASSISTANT_V2"
    disclaimer: str = "General wellness guidance, not medical advice."


class AccountDeleteRequest(BaseModel):
    confirmation: Literal["DELETE"]


class ProductStore:
    def __init__(self) -> None:
        self.profiles: dict[str, HealthProfile] = {}
        self.account_profiles: dict[str, AccountProfileRecord] = {}
        self.household_profiles: dict[str, dict[str, HouseholdProfile]] = {}
        self.diary: dict[str, dict[str, DiaryEntry]] = {}
        self.pantry: dict[str, dict[str, PantryItem]] = {}
        self.shopping_list: dict[str, dict[str, ShoppingListItem]] = {}
        self.favorites: dict[str, dict[str, FavoriteFood]] = {}
        self.notifications: dict[str, dict[str, Notification]] = {}
        self.assistant_usage: dict[tuple[str, date], int] = {}
        self.lock = RLock()

    def get_profile(self, user_id: str) -> HealthProfile:
        if postgres_store is not None:
            payload = postgres_store.get_profile(user_id)
            return HealthProfile.model_validate(payload) if payload else HealthProfile()
        return self.profiles.get(user_id, HealthProfile())

    def put_profile(self, user_id: str, profile: HealthProfile) -> None:
        if postgres_store is not None:
            postgres_store.put_profile(user_id, profile.model_dump(mode="json"))
            return
        with self.lock:
            self.profiles[user_id] = profile

    def get_account_profile(self, user_id: str, default_name: str) -> AccountProfileRecord:
        if postgres_store is not None:
            payload = postgres_store.get_account_profile(user_id)
            if payload:
                return AccountProfileRecord.model_validate(payload)
        normalized_name = default_name.strip()[:100]
        if len(normalized_name) < 2:
            normalized_name = "NutriLens user"
        return self.account_profiles.get(user_id, AccountProfileRecord(full_name=normalized_name))

    def put_account_profile(self, user_id: str, profile: AccountProfileRecord) -> None:
        if postgres_store is not None:
            postgres_store.put_account_profile(user_id, profile.model_dump(mode="json"))
            return
        with self.lock:
            self.account_profiles[user_id] = profile

    def list_household_profiles(self, user_id: str) -> list[HouseholdProfile]:
        if postgres_store is not None:
            return [
                HouseholdProfile.model_validate(item)
                for item in postgres_store.list_household_profiles(user_id)
            ]
        return sorted(
            self.household_profiles.get(user_id, {}).values(),
            key=lambda item: (item.created_at, item.id),
        )

    def add_household_profile(self, user_id: str, profile: HouseholdProfile) -> bool:
        if postgres_store is not None:
            return postgres_store.add_household_profile(
                user_id, profile.id, profile.model_dump(mode="json"), limit=10
            )
        with self.lock:
            profiles = self.household_profiles.setdefault(user_id, {})
            if len(profiles) >= 10:
                return False
            profiles[profile.id] = profile
            return True

    def update_household_profile(self, user_id: str, profile: HouseholdProfile) -> bool:
        if postgres_store is not None:
            return postgres_store.update_household_profile(
                user_id, profile.id, profile.model_dump(mode="json")
            )
        with self.lock:
            profiles = self.household_profiles.get(user_id, {})
            if profile.id not in profiles:
                return False
            profiles[profile.id] = profile
            return True

    def delete_household_profile(self, user_id: str, profile_id: str) -> bool:
        if postgres_store is not None:
            return postgres_store.delete_household_profile(user_id, profile_id)
        with self.lock:
            return self.household_profiles.get(user_id, {}).pop(profile_id, None) is not None

    def list_diary(self, user_id: str, cutoff: datetime) -> list[DiaryEntry]:
        if postgres_store is not None:
            return [
                DiaryEntry.model_validate(item)
                for item in postgres_store.list_diary(user_id, cutoff)
            ]
        return sorted(
            (item for item in self.diary.get(user_id, {}).values() if item.eaten_at >= cutoff),
            key=lambda item: item.eaten_at,
            reverse=True,
        )

    def add_diary(self, user_id: str, entry: DiaryEntry) -> None:
        if postgres_store is not None:
            postgres_store.add_diary(
                user_id, entry.id, entry.eaten_at, entry.model_dump(mode="json")
            )
            return
        with self.lock:
            self.diary.setdefault(user_id, {})[entry.id] = entry

    def delete_diary(self, user_id: str, entry_id: str) -> bool:
        if postgres_store is not None:
            return postgres_store.delete_diary(user_id, entry_id)
        with self.lock:
            return self.diary.get(user_id, {}).pop(entry_id, None) is not None

    def update_diary(self, user_id: str, entry: DiaryEntry) -> bool:
        if postgres_store is not None:
            return postgres_store.update_diary(
                user_id,
                entry.id,
                entry.eaten_at,
                entry.model_dump(mode="json"),
            )
        with self.lock:
            entries = self.diary.get(user_id, {})
            if entry.id not in entries:
                return False
            entries[entry.id] = entry
            return True

    def list_pantry(self, user_id: str) -> list[PantryItem]:
        if postgres_store is not None:
            return [PantryItem.model_validate(item) for item in postgres_store.list_pantry(user_id)]
        return list(self.pantry.get(user_id, {}).values())

    def add_pantry(self, user_id: str, item: PantryItem) -> None:
        if postgres_store is not None:
            postgres_store.add_pantry(user_id, item.id, item.model_dump(mode="json"))
            return
        with self.lock:
            self.pantry.setdefault(user_id, {})[item.id] = item

    def update_pantry(self, user_id: str, item: PantryItem) -> bool:
        if postgres_store is not None:
            return postgres_store.update_pantry(user_id, item.id, item.model_dump(mode="json"))
        with self.lock:
            items = self.pantry.get(user_id, {})
            if item.id not in items:
                return False
            items[item.id] = item
            return True

    def delete_pantry(self, user_id: str, item_id: str) -> bool:
        if postgres_store is not None:
            return postgres_store.delete_pantry(user_id, item_id)
        with self.lock:
            return self.pantry.get(user_id, {}).pop(item_id, None) is not None

    def list_shopping_list(self, user_id: str) -> list[ShoppingListItem]:
        if postgres_store is not None:
            return [
                ShoppingListItem.model_validate(item)
                for item in postgres_store.list_shopping_list(user_id)
            ]
        return sorted(
            self.shopping_list.get(user_id, {}).values(),
            key=lambda item: (item.checked, item.created_at, item.id),
        )

    def add_shopping_list_item(self, user_id: str, item: ShoppingListItem) -> None:
        if postgres_store is not None:
            postgres_store.add_shopping_list_item(user_id, item.id, item.model_dump(mode="json"))
            return
        with self.lock:
            self.shopping_list.setdefault(user_id, {})[item.id] = item

    def update_shopping_list_item(self, user_id: str, item: ShoppingListItem) -> bool:
        if postgres_store is not None:
            return postgres_store.update_shopping_list_item(
                user_id, item.id, item.model_dump(mode="json")
            )
        with self.lock:
            items = self.shopping_list.get(user_id, {})
            if item.id not in items:
                return False
            items[item.id] = item
            return True

    def delete_shopping_list_item(self, user_id: str, item_id: str) -> bool:
        if postgres_store is not None:
            return postgres_store.delete_shopping_list_item(user_id, item_id)
        with self.lock:
            return self.shopping_list.get(user_id, {}).pop(item_id, None) is not None

    def delete_generated_shopping_item(self, user_id: str, pantry_item_id: str) -> None:
        if postgres_store is not None:
            postgres_store.delete_generated_shopping_item(user_id, pantry_item_id)
            return
        with self.lock:
            items = self.shopping_list.get(user_id, {})
            for item_id in [
                item.id
                for item in items.values()
                if item.source == "LOW_STOCK" and item.pantry_item_id == pantry_item_id
            ]:
                items.pop(item_id, None)

    def upsert_favorite(self, user_id: str, favorite: FavoriteFood) -> None:
        if postgres_store is not None:
            postgres_store.upsert_favorite(
                user_id,
                favorite.scan_id,
                favorite.model_dump(mode="json"),
            )
            return
        with self.lock:
            existing = self.favorites.setdefault(user_id, {}).get(favorite.scan_id)
            self.favorites[user_id][favorite.scan_id] = (
                favorite.model_copy(update={"saved_at": existing.saved_at})
                if existing is not None
                else favorite
            )

    def list_favorites(self, user_id: str, limit: int) -> list[FavoriteFood]:
        if postgres_store is not None:
            return [
                FavoriteFood.model_validate(item)
                for item in postgres_store.list_favorites(user_id)[:limit]
            ]
        return sorted(
            self.favorites.get(user_id, {}).values(),
            key=lambda item: item.saved_at,
            reverse=True,
        )[:limit]

    def delete_favorite(self, user_id: str, scan_id: str) -> bool:
        if postgres_store is not None:
            return postgres_store.delete_favorite(user_id, scan_id)
        with self.lock:
            return self.favorites.get(user_id, {}).pop(scan_id, None) is not None

    def upsert_notification(self, user_id: str, notification: Notification) -> None:
        if postgres_store is not None:
            postgres_store.upsert_notification(user_id, notification.model_dump(mode="python"))
            return
        with self.lock:
            existing = self.notifications.setdefault(user_id, {}).get(notification.id)
            self.notifications[user_id][notification.id] = (
                notification.model_copy(update={"read_at": existing.read_at})
                if existing is not None
                else notification
            )

    def list_notifications(self, user_id: str, limit: int) -> list[Notification]:
        if postgres_store is not None:
            return [
                Notification.model_validate(item)
                for item in postgres_store.list_notifications(user_id, limit)
            ]
        return sorted(
            self.notifications.get(user_id, {}).values(),
            key=lambda item: item.created_at,
            reverse=True,
        )[:limit]

    def mark_notification_read(self, user_id: str, notification_id: str) -> Notification | None:
        if postgres_store is not None:
            if not postgres_store.mark_notification_read(user_id, notification_id):
                return None
            return next(
                (
                    item
                    for item in self.list_notifications(user_id, 100)
                    if item.id == notification_id
                ),
                None,
            )
        with self.lock:
            notification = self.notifications.get(user_id, {}).get(notification_id)
            if notification is None:
                return None
            updated = notification.model_copy(
                update={"read_at": notification.read_at or datetime.now(UTC)}
            )
            self.notifications[user_id][notification_id] = updated
            return updated

    def mark_all_notifications_read(self, user_id: str) -> int:
        if postgres_store is not None:
            return postgres_store.mark_all_notifications_read(user_id)
        with self.lock:
            unread = [
                item
                for item in self.notifications.get(user_id, {}).values()
                if item.read_at is None
            ]
            for notification in unread:
                self.notifications[user_id][notification.id] = notification.model_copy(
                    update={"read_at": datetime.now(UTC)}
                )
            return len(unread)

    def delete_notification(self, user_id: str, notification_id: str) -> bool:
        if postgres_store is not None:
            return postgres_store.delete_notification(user_id, notification_id)
        with self.lock:
            return self.notifications.get(user_id, {}).pop(notification_id, None) is not None

    def read_assistant_usage(self, user_id: str, day: date) -> int:
        if postgres_store is not None:
            return postgres_store.read_assistant_usage(user_id, day)
        with self.lock:
            return self.assistant_usage.get((user_id, day), 0)

    def reserve_assistant(self, user_id: str, day: date, limit: int) -> int | None:
        if postgres_store is not None:
            return postgres_store.reserve_assistant_usage(user_id, day, limit)
        key = (user_id, day)
        with self.lock:
            used = self.assistant_usage.get(key, 0)
            if used >= limit:
                return None
            self.assistant_usage[key] = used + 1
            return used + 1

    def release_assistant(self, user_id: str, day: date) -> int:
        if postgres_store is not None:
            return postgres_store.release_assistant_usage(user_id, day)
        key = (user_id, day)
        with self.lock:
            used = self.assistant_usage.get(key, 0)
            new_used = max(0, used - 1)
            self.assistant_usage[key] = new_used
            return new_used

    def increment_assistant(self, user_id: str, day: date, limit: int) -> int | None:
        return self.reserve_assistant(user_id, day, limit)

    def research_summary(self) -> tuple[int, int, NutrientSnapshot]:
        if postgres_store is not None:
            user_count, entry_count, stored_totals = postgres_store.research_nutrition_summary()
            return user_count, entry_count, NutrientSnapshot.model_validate(stored_totals)
        consented_user_ids = {
            user_id
            for user_id, profile in self.account_profiles.items()
            if profile.research_insights_consent
        }
        active_diaries = [
            diary_entries
            for user_id, diary_entries in self.diary.items()
            if diary_entries and user_id in consented_user_ids
        ]
        aggregate_totals = _sum_nutrients(
            entry.nutrients for diary in active_diaries for entry in diary.values()
        )
        return (
            len(active_diaries),
            sum(len(diary_entries) for diary_entries in active_diaries),
            aggregate_totals,
        )

    def clear_user(self, user_id: str) -> None:
        if postgres_store is not None:
            return
        with self.lock:
            self.profiles.pop(user_id, None)
            self.account_profiles.pop(user_id, None)
            self.household_profiles.pop(user_id, None)
            self.diary.pop(user_id, None)
            self.pantry.pop(user_id, None)
            self.shopping_list.pop(user_id, None)
            self.favorites.pop(user_id, None)
            self.notifications.pop(user_id, None)
            for key in [key for key in self.assistant_usage if key[0] == user_id]:
                self.assistant_usage.pop(key, None)


product_store = ProductStore()


def _profile(user_id: str) -> HealthProfile:
    return product_store.get_profile(user_id)


def _mask_phone(phone_number: str | None) -> str | None:
    if phone_number is None:
        return None
    return f"+{'•' * max(4, len(phone_number) - 5)}{phone_number[-4:]}"


def _account_profile_response(profile: AccountProfileRecord, user: User) -> AccountProfileResponse:
    return AccountProfileResponse(
        full_name=profile.full_name,
        date_of_birth=profile.date_of_birth,
        masked_phone_number=_mask_phone(profile.phone_number),
        phone_state=profile.phone_state,
        phone_verification_availability=(
            "READY" if settings.phone_auth_enabled else "BLOCKED_EXTERNAL_COST"
        ),
        country_region=profile.country_region,
        unit_system=profile.unit_system,
        research_insights_consent=profile.research_insights_consent,
        onboarding_complete=profile.onboarding_completed_at is not None,
        age_eligibility=("ELIGIBLE_18_PLUS" if profile.date_of_birth else "UNKNOWN"),
        legal_acceptance_complete=(
            user.terms_accepted_at is not None and user.privacy_accepted_at is not None
        ),
    )


def _entitlements(user: User) -> dict[str, int | bool]:
    return resolve_entitlements(user.plan, user.subscription_status, set(user.roles)).values


@router.get("/account/profile", response_model=AccountProfileResponse)
def get_account_profile(
    user: Annotated[User, Depends(current_user)],
) -> AccountProfileResponse:
    return _account_profile_response(product_store.get_account_profile(user.id, user.name), user)


@router.put("/account/profile", response_model=AccountProfileResponse)
def update_account_profile(
    payload: AccountProfileUpdate,
    user: Annotated[User, Depends(current_user)],
) -> AccountProfileResponse:
    existing = product_store.get_account_profile(user.id, user.name)
    legal_complete = user.terms_accepted_at is not None and user.privacy_accepted_at is not None
    if payload.complete_onboarding and not legal_complete:
        if not (payload.accepted_terms and payload.accepted_privacy):
            raise HTTPException(
                status_code=422,
                detail="Accept the Terms of Use and Privacy Policy to complete onboarding.",
            )
        accepted_user = user_store.accept_legal(user.id)
        if accepted_user is None:
            raise HTTPException(status_code=404, detail="Account not found.")
        user = accepted_user
    phone_number = existing.phone_number
    phone_state = existing.phone_state
    if payload.phone_update == "REMOVE":
        phone_number = None
        phone_state = "NOT_ADDED"
    elif payload.phone_update == "SET":
        phone_number = payload.phone_number
        if phone_number != existing.phone_number:
            phone_state = "UNVERIFIED"

    completed_at = existing.onboarding_completed_at
    if payload.complete_onboarding and completed_at is None:
        completed_at = datetime.now(UTC)
    elif payload.date_of_birth is None:
        completed_at = None

    updated = AccountProfileRecord(
        full_name=payload.full_name,
        date_of_birth=payload.date_of_birth,
        phone_number=phone_number,
        phone_state=phone_state,
        country_region=payload.country_region,
        unit_system=payload.unit_system,
        research_insights_consent=payload.research_insights_consent,
        onboarding_completed_at=completed_at,
    )
    product_store.put_account_profile(user.id, updated)
    if user_store.update_display_name(user.id, updated.full_name) is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    user_store.record_security_event(user_id=user.id, event_type="account_profile_updated")
    return _account_profile_response(updated, user)


@router.get("/profile", response_model=HealthProfile)
def get_profile(user: Annotated[User, Depends(current_user)]) -> HealthProfile:
    return _profile(user.id)


@router.put("/profile", response_model=HealthProfile)
def update_profile(
    profile: HealthProfile, user: Annotated[User, Depends(current_user)]
) -> HealthProfile:
    product_store.put_profile(user.id, profile)
    return profile


@router.delete("/profile", response_model=HealthProfile)
def delete_profile(user: Annotated[User, Depends(current_user)]) -> HealthProfile:
    """Clear health conditions, dietary style, goals, and reset profile to default."""
    default_profile = HealthProfile()
    product_store.put_profile(user.id, default_profile)
    user_store.record_security_event(user_id=user.id, event_type="health_profile_reset")
    return default_profile


@router.get("/profile/bmi-context", response_model=BmiContextResponse)
def get_bmi_context(
    user: Annotated[User, Depends(current_user)],
) -> BmiContextResponse:
    context = _profile(user.id).body_context
    if (
        not context.consent_bmi_context
        or not context.adult_attestation
        or context.height_cm is None
        or context.weight_kg is None
    ):
        return BmiContextResponse(
            state="NOT_CONFIGURED",
            bmi=None,
            height_cm=None,
            weight_kg=None,
        )
    height_m = context.height_cm / 100
    return BmiContextResponse(
        state="AVAILABLE",
        bmi=round(context.weight_kg / (height_m * height_m), 2),
        height_cm=context.height_cm,
        weight_kg=context.weight_kg,
    )


@router.get("/profile/household", response_model=list[HouseholdProfile])
def list_household_profiles(
    user: Annotated[User, Depends(current_user)],
) -> list[HouseholdProfile]:
    return product_store.list_household_profiles(user.id)


@router.post(
    "/profile/household",
    response_model=HouseholdProfile,
    status_code=status.HTTP_201_CREATED,
)
def create_household_profile(
    payload: HouseholdProfileInput,
    user: Annotated[User, Depends(current_user)],
) -> HouseholdProfile:
    now = datetime.now(UTC)
    profile = HouseholdProfile(
        id=str(uuid4()), created_at=now, updated_at=now, **payload.model_dump()
    )
    if not product_store.add_household_profile(user.id, profile):
        raise HTTPException(status_code=409, detail="Household profile limit reached (10).")
    return profile


@router.put("/profile/household/{profile_id}", response_model=HouseholdProfile)
def update_household_profile(
    profile_id: str,
    payload: HouseholdProfileInput,
    user: Annotated[User, Depends(current_user)],
) -> HouseholdProfile:
    existing = next(
        (item for item in product_store.list_household_profiles(user.id) if item.id == profile_id),
        None,
    )
    if existing is None:
        raise HTTPException(status_code=404, detail="Household profile not found.")
    updated = HouseholdProfile(
        id=existing.id,
        created_at=existing.created_at,
        updated_at=datetime.now(UTC),
        **payload.model_dump(),
    )
    if not product_store.update_household_profile(user.id, updated):
        raise HTTPException(status_code=404, detail="Household profile not found.")
    return updated


@router.delete(
    "/profile/household/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_household_profile(
    profile_id: str,
    user: Annotated[User, Depends(current_user)],
) -> Response:
    if not product_store.delete_household_profile(user.id, profile_id):
        raise HTTPException(status_code=404, detail="Household profile not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/favorites", response_model=list[FavoriteFood])
def list_favorites(
    user: Annotated[User, Depends(current_user)],
    limit: int = Query(default=50, ge=1, le=100),
) -> list[FavoriteFood]:
    return product_store.list_favorites(user.id, limit)


@router.put("/favorites/{scan_id}", response_model=FavoriteFood)
def save_favorite(scan_id: str, user: Annotated[User, Depends(current_user)]) -> FavoriteFood:
    try:
        scan = get_owned_scan_result(scan_id, user)
    except ScanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Scan not found.") from exc
    favorite = FavoriteFood(
        scan_id=scan_id,
        product_name=(
            scan.product_name_candidates[0].value if scan.product_name_candidates else None
        ),
        brand=scan.brand_candidates[0].value if scan.brand_candidates else None,
    )
    product_store.upsert_favorite(user.id, favorite)
    return next(
        item for item in product_store.list_favorites(user.id, 100) if item.scan_id == scan_id
    )


@router.delete(
    "/favorites/{scan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def remove_favorite(scan_id: str, user: Annotated[User, Depends(current_user)]) -> Response:
    if not product_store.delete_favorite(user.id, scan_id):
        raise HTTPException(status_code=404, detail="Favorite not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/search", response_model=UniversalSearchResponse)
def universal_search(
    user: Annotated[User, Depends(current_user)],
    q: str = Query(min_length=2, max_length=100),
    limit: int = Query(default=10, ge=1, le=20),
) -> UniversalSearchResponse:
    normalized = q.strip().casefold()
    if len(normalized) < 2:
        raise HTTPException(status_code=422, detail="Search query is too short.")
    scan_items: list[UniversalSearchItem] = []
    for scan in _owned_scans(user)[:100]:
        name = scan.product_name_candidates[0].value if scan.product_name_candidates else ""
        brand = scan.brand_candidates[0].value if scan.brand_candidates else ""
        if normalized not in name.casefold() and normalized not in brand.casefold():
            continue
        scan_items.append(
            UniversalSearchItem(
                kind="SCAN",
                id=scan.scan_id,
                title=name or "Unidentified food scan",
                subtitle=brand or "Brand not resolved",
                score=1.0 if normalized in {name.casefold(), brand.casefold()} else 0.8,
            )
        )
    knowledge_items = [
        UniversalSearchItem(
            kind=match.record.record_type,
            id=match.record.taxonomy_id or f"unknown:{index}",
            title=match.record.canonical_name or "Unresolved taxonomy record",
            subtitle=(
                match.record.functional_category
                or (
                    f"FoodOn: {match.record.foodon_ids[0].rsplit('/', 1)[-1]}"
                    if match.record.foodon_ids
                    else None
                )
                or match.record.source_dataset
                or "Governed taxonomy record"
            ),
            score=match.score,
        )
        for index, match in enumerate(retrieve_knowledge(q, min(limit, 10)))
        if match.record.record_type != "UNKNOWN"
    ]
    substitution_items = [
        UniversalSearchItem(
            kind="SUBSTITUTION",
            id=f"substitution:{match.mapping.ingredient}",
            title=f"Alternatives for {match.mapping.ingredient}",
            subtitle=(
                f"{', '.join(match.mapping.alternatives)} · {match.mapping.function}. "
                f"{match.mapping.limitation}"
            ),
            score=match.score,
        )
        for match in retrieve_alternative_ingredients(q, min(limit, 10))
    ]
    items = sorted(
        [*scan_items, *knowledge_items, *substitution_items],
        key=lambda item: (-item.score, item.kind, item.title.casefold()),
    )[:limit]
    return UniversalSearchResponse(query=q.strip(), items=items)


@router.get("/account/export")
def export_account(user: Annotated[User, Depends(current_user)]) -> dict[str, object]:
    diary = product_store.list_diary(user.id, datetime.min.replace(tzinfo=UTC))
    account_profile = product_store.get_account_profile(user.id, user.name)
    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "account": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "plan": user.plan.value,
            "subscription_status": user.subscription_status.value,
            "roles": sorted(role.value for role in user.roles),
        },
        "account_profile": account_profile.model_dump(mode="json"),
        "profile": product_store.get_profile(user.id).model_dump(mode="json"),
        "household_profiles": [
            item.model_dump(mode="json") for item in product_store.list_household_profiles(user.id)
        ],
        "diary": [entry.model_dump(mode="json") for entry in diary],
        "hydration": hydration_store.export_user(user.id),
        "weight": weight_store.export_user(user.id),
        "custom_recipes": custom_recipe_store.export_user(user.id),
        "pantry": [item.model_dump(mode="json") for item in product_store.list_pantry(user.id)],
        "shopping_list": [
            item.model_dump(mode="json") for item in product_store.list_shopping_list(user.id)
        ],
        "favorites": [
            item.model_dump(mode="json") for item in product_store.list_favorites(user.id, 100)
        ],
        "scan_documents": (
            postgres_store.list_scans(user.id)
            if postgres_store is not None
            else (
                "Structured local-development scans are process-local; "
                "raw images are never retained."
            )
        ),
    }


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_account(
    payload: AccountDeleteRequest,
    user: Annotated[User, Depends(current_user)],
) -> Response:
    del payload
    product_store.clear_user(user.id)
    if not user_store.delete(user.id):
        raise HTTPException(status_code=404, detail="Account not found.")
    hydration_store.clear_user(user.id)
    weight_store.clear_user(user.id)
    custom_recipe_store.clear_user(user.id)
    # Import locally because recipe actions consume the product response models.
    # This runs outside ProductStore.lock to preserve the action/store lock order.
    from backend.custom_recipe_actions_api import recipe_action_store

    recipe_action_store.clear_user(user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/diary", response_model=list[DiaryEntry])
def list_diary(user: Annotated[User, Depends(current_user)]) -> list[DiaryEntry]:
    history_days = int(_entitlements(user)["diary.history_days"])
    cutoff = datetime.now(UTC) - timedelta(days=history_days)
    return product_store.list_diary(user.id, cutoff)


@router.post("/diary", response_model=DiaryEntry, status_code=status.HTTP_201_CREATED)
def create_diary(payload: DiaryCreate, user: Annotated[User, Depends(current_user)]) -> DiaryEntry:
    if payload.scan_id is not None:
        _require_owned_product_scan(payload.scan_id, user)
    entry = DiaryEntry(
        id=str(uuid4()),
        source="SCAN" if payload.scan_id is not None else "MANUAL",
        **payload.model_dump(),
    )
    product_store.add_diary(user.id, entry)
    return entry


@router.delete("/diary/{entry_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_diary(entry_id: str, user: Annotated[User, Depends(current_user)]) -> Response:
    if not product_store.delete_diary(user.id, entry_id):
        raise HTTPException(status_code=404, detail="Diary entry not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/diary/{entry_id}", response_model=DiaryEntry)
def update_diary(
    entry_id: str,
    payload: DiaryUpdate,
    user: Annotated[User, Depends(current_user)],
) -> DiaryEntry:
    current = next(
        (
            entry
            for entry in product_store.list_diary(user.id, datetime.min.replace(tzinfo=UTC))
            if entry.id == entry_id
        ),
        None,
    )
    if current is None:
        raise HTTPException(status_code=404, detail="Diary entry not found.")
    if payload.scan_id is not None:
        _require_owned_product_scan(payload.scan_id, user)
    updates = payload.model_dump(exclude_unset=True)
    for required_field in ("name", "eaten_at", "nutrients"):
        if updates.get(required_field) is None:
            updates.pop(required_field, None)
    if {"name", "serving_grams", "nutrients", "scan_id"}.intersection(updates):
        updates.update(recipe_id=None, recipe_version=None, recipe_servings=None)
        updates["source"] = "SCAN" if updates.get("scan_id") else "MANUAL"
    updated = DiaryEntry.model_validate({**current.model_dump(), **updates})
    if not product_store.update_diary(user.id, updated):
        raise HTTPException(status_code=404, detail="Diary entry not found.")
    return updated


@router.post("/diary/compare", response_model=MealComparisonResponse)
def compare_diary_entries(
    payload: MealComparisonRequest,
    user: Annotated[User, Depends(current_user)],
) -> MealComparisonResponse:
    if len(set(payload.entry_ids)) != len(payload.entry_ids):
        raise HTTPException(status_code=422, detail="Diary entry IDs must be unique.")
    owned_entries = {
        entry.id: entry
        for entry in product_store.list_diary(user.id, datetime.min.replace(tzinfo=UTC))
    }
    if any(entry_id not in owned_entries for entry_id in payload.entry_ids):
        raise HTTPException(status_code=404, detail="One or more diary entries were not found.")
    candidates: list[MealComparisonCandidate] = []
    for entry_id in payload.entry_ids:
        entry = owned_entries[entry_id]
        factor = 100 / entry.serving_grams if entry.serving_grams is not None else None
        candidates.append(
            MealComparisonCandidate(
                entry_id=entry.id,
                name=entry.name,
                eaten_at=entry.eaten_at,
                serving_grams=entry.serving_grams,
                logged_serving=entry.nutrients,
                per_100g=_scale_nutrients(entry.nutrients, factor),
            )
        )
    return MealComparisonResponse(
        candidates=candidates,
        compared_nutrients=list(NutrientSnapshot.model_fields),
    )


@router.get("/pantry", response_model=list[PantryItem])
def list_pantry(user: Annotated[User, Depends(current_user)]) -> list[PantryItem]:
    return product_store.list_pantry(user.id)


@router.post("/pantry", response_model=PantryItem, status_code=status.HTTP_201_CREATED)
def create_pantry(
    payload: PantryCreate, user: Annotated[User, Depends(current_user)]
) -> PantryItem:
    items = product_store.list_pantry(user.id)
    maximum = int(_entitlements(user)["pantry.max_items"])
    if len(items) >= maximum:
        raise HTTPException(status_code=403, detail="Pantry item allowance reached.")
    item = PantryItem(id=str(uuid4()), **payload.model_dump())
    product_store.add_pantry(user.id, item)
    _create_expiry_notification(user.id, item)
    _create_low_stock_notification(user.id, item)
    return item


@router.delete("/pantry/{item_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_pantry(item_id: str, user: Annotated[User, Depends(current_user)]) -> Response:
    if not product_store.delete_pantry(user.id, item_id):
        raise HTTPException(status_code=404, detail="Pantry item not found.")
    product_store.delete_notification(user.id, f"pantry-expiry:{item_id}")
    product_store.delete_notification(user.id, f"pantry-low-stock:{item_id}")
    product_store.delete_generated_shopping_item(user.id, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/pantry/{item_id}", response_model=PantryItem)
def update_pantry(
    item_id: str,
    payload: PantryUpdate,
    user: Annotated[User, Depends(current_user)],
) -> PantryItem:
    current = next(
        (item for item in product_store.list_pantry(user.id) if item.id == item_id),
        None,
    )
    if current is None:
        raise HTTPException(status_code=404, detail="Pantry item not found.")
    updates = payload.model_dump(exclude_unset=True)
    for required_field in ("name", "quantity", "unit", "item_role"):
        if updates.get(required_field) is None:
            updates.pop(required_field, None)
    updated = PantryItem.model_validate({**current.model_dump(), **updates})
    if not product_store.update_pantry(user.id, updated):
        raise HTTPException(status_code=404, detail="Pantry item not found.")
    _create_expiry_notification(user.id, updated)
    _create_low_stock_notification(user.id, updated)
    if updated.low_stock_threshold is None or updated.quantity > updated.low_stock_threshold:
        product_store.delete_generated_shopping_item(user.id, item_id)
    return updated


@router.get("/pantry/low-stock", response_model=LowStockResponse)
def low_stock_pantry(user: Annotated[User, Depends(current_user)]) -> LowStockResponse:
    items = [
        item
        for item in product_store.list_pantry(user.id)
        if item.low_stock_threshold is not None and item.quantity <= item.low_stock_threshold
    ]
    return LowStockResponse(items=sorted(items, key=lambda item: (item.name.casefold(), item.id)))


@router.get("/shopping-list", response_model=list[ShoppingListItem])
def list_shopping_list(
    user: Annotated[User, Depends(current_user)],
) -> list[ShoppingListItem]:
    return product_store.list_shopping_list(user.id)


@router.post("/shopping-list", response_model=ShoppingListItem, status_code=status.HTTP_201_CREATED)
def create_shopping_list_item(
    payload: ShoppingListCreate,
    user: Annotated[User, Depends(current_user)],
) -> ShoppingListItem:
    current = product_store.list_shopping_list(user.id)
    norm_name = payload.name.strip().casefold()
    existing = next(
        (
            item
            for item in current
            if not item.checked and item.name.strip().casefold() == norm_name
        ),
        None,
    )
    if existing is not None:
        # If payload has quantity and matching unit, combine/update quantity
        if payload.quantity is not None and (existing.unit == payload.unit or not existing.unit):
            updated_qty = (existing.quantity or 0.0) + payload.quantity
            updated = ShoppingListItem.model_validate(
                {
                    **existing.model_dump(),
                    "quantity": round(updated_qty, 2),
                    "unit": payload.unit or existing.unit,
                    "recipe_id": payload.recipe_id or existing.recipe_id,
                }
            )
            product_store.update_shopping_list_item(user.id, updated)
            return updated
        return existing
    if len(current) >= 200:
        raise HTTPException(status_code=403, detail="Shopping-list item allowance reached.")
    item = ShoppingListItem(
        id=str(uuid4()),
        name=payload.name,
        quantity=payload.quantity,
        unit=payload.unit,
        recipe_id=payload.recipe_id,
        source="RECIPE_PLAN" if payload.recipe_id else "USER_ADDED",
    )
    product_store.add_shopping_list_item(user.id, item)
    return item


@router.patch("/shopping-list/{item_id}", response_model=ShoppingListItem)
def update_shopping_list_item(
    item_id: str,
    payload: ShoppingListUpdate,
    user: Annotated[User, Depends(current_user)],
) -> ShoppingListItem:
    current = next(
        (item for item in product_store.list_shopping_list(user.id) if item.id == item_id),
        None,
    )
    if current is None:
        raise HTTPException(status_code=404, detail="Shopping-list item not found.")
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("name") is None:
        updates.pop("name", None)
    updates.pop("source", None)
    updated = ShoppingListItem.model_validate(
        {**current.model_dump(), **updates, "source": current.source}
    )
    if not product_store.update_shopping_list_item(user.id, updated):
        raise HTTPException(status_code=404, detail="Shopping-list item not found.")
    return updated


@router.delete(
    "/shopping-list/{item_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def delete_shopping_list_item(
    item_id: str,
    user: Annotated[User, Depends(current_user)],
) -> Response:
    if not product_store.delete_shopping_list_item(user.id, item_id):
        raise HTTPException(status_code=404, detail="Shopping-list item not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/shopping-list/from-low-stock", response_model=ShoppingListGenerationResponse)
def generate_shopping_list_from_low_stock(
    user: Annotated[User, Depends(current_user)],
) -> ShoppingListGenerationResponse:
    current = product_store.list_shopping_list(user.id)
    existing_names = {item.name.casefold() for item in current}
    generated = 0
    for pantry_item in low_stock_pantry(user).items:
        if pantry_item.name.casefold() in existing_names or len(current) >= 200:
            continue
        item = ShoppingListItem(
            id=str(uuid4()),
            name=pantry_item.name,
            source="LOW_STOCK",
            pantry_item_id=pantry_item.id,
        )
        product_store.add_shopping_list_item(user.id, item)
        current.append(item)
        existing_names.add(item.name.casefold())
        generated += 1
    return ShoppingListGenerationResponse(
        generated_count=generated,
        items=product_store.list_shopping_list(user.id),
    )


@router.get("/notifications", response_model=list[Notification])
def list_notifications(
    user: Annotated[User, Depends(current_user)],
    limit: int = Query(default=20, ge=1, le=100),
) -> list[Notification]:
    return product_store.list_notifications(user.id, limit)


@router.patch("/notifications/{notification_id}/read", response_model=Notification)
def mark_notification_read(
    notification_id: str,
    user: Annotated[User, Depends(current_user)],
) -> Notification:
    notification = product_store.mark_notification_read(user.id, notification_id)
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    return notification


@router.post("/notifications/read-all")
def mark_all_notifications_read(
    user: Annotated[User, Depends(current_user)],
) -> dict[str, int]:
    return {"updated": product_store.mark_all_notifications_read(user.id)}


@router.get("/recipes/recommendations", response_model=list[RecipeRecommendation])
def recipe_recommendations(
    user: Annotated[User, Depends(current_user)],
    mode: Literal[
        "COOK_WITH_WHAT_I_HAVE",
        "USE_SELECTED_INGREDIENTS",
        "USE_EXPIRING_SOON",
        "USE_LEFTOVERS",
        "PLAN_A_RECIPE",
    ] = "COOK_WITH_WHAT_I_HAVE",
    selected_ingredients: Annotated[list[str] | None, Query()] = None,
    servings: Annotated[float, Query(gt=0, le=100)] = 1.0,
) -> list[RecipeRecommendation]:
    pantry_items = product_store.list_pantry(user.id)
    today = datetime.now(UTC).date()
    active_pantry = [
        item for item in pantry_items if item.expires_on is None or item.expires_on >= today
    ]
    if mode == "COOK_WITH_WHAT_I_HAVE" and not active_pantry:
        return []

    user_profile = _profile(user.id)
    profile_exclusions: set[str] = set()
    if user_profile:
        profile_exclusions.update(s.casefold() for s in user_profile.allergens)
        profile_exclusions.update(s.casefold() for s in user_profile.intolerances)
        profile_exclusions.update(s.casefold() for s in user_profile.food_exclusions)

    pantry_names = [item.name.casefold() for item in active_pantry]
    bundle = _recipe_bundle()
    recommendations: list[RecipeRecommendation] = []

    for template in bundle["templates"]:
        required = [str(item) for item in template["required"]]
        optional = [str(item) for item in template.get("optional", [])]
        all_recipe_ingredients = [r.casefold() for r in required + optional]

        if any(exc in ing for exc in profile_exclusions for ing in all_recipe_ingredients):
            continue

        is_vegan_conflict = (
            user_profile is not None
            and user_profile.dietary_style == "Vegan"
            and any(
                dairy in ing
                for dairy in {"paneer", "milk", "yogurt", "ghee", "butter", "cheese", "egg"}
                for ing in all_recipe_ingredients
            )
        )
        if is_vegan_conflict:
            continue

        details = {d["name"].casefold(): d for d in template.get("ingredient_details", [])}

        available_required: list[str] = []
        missing_required: list[str] = []
        deficits: list[IngredientDeficit] = []

        for req in required:
            req_norm = req.casefold()
            matched = [
                item for item in active_pantry if _pantry_contains([item.name.casefold()], req)
            ]
            detail = details.get(req_norm)

            if not matched:
                missing_required.append(req)
                if detail:
                    req_qty = round(float(detail["quantity"]) * servings, 2)
                    req_u = str(detail["unit"])
                    deficits.append(
                        IngredientDeficit(
                            ingredient=req,
                            required_quantity=req_qty,
                            available_quantity=0.0,
                            missing_quantity=req_qty,
                            unit=req_u,
                            status="MISSING",
                        )
                    )
                else:
                    deficits.append(IngredientDeficit(ingredient=req, status="MISSING"))
            else:
                if detail:
                    req_qty = round(float(detail["quantity"]) * servings, 2)
                    req_u = str(detail["unit"])
                    avail_sum = 0.0
                    uncertain = False
                    for m in matched:
                        conv = _convert_quantity(m.quantity or 0.0, m.unit or "", req_u)
                        if conv is None:
                            uncertain = True
                        else:
                            avail_sum += conv
                    if uncertain and avail_sum < req_qty:
                        available_required.append(req)
                        deficits.append(
                            IngredientDeficit(
                                ingredient=req,
                                required_quantity=req_qty,
                                available_quantity=round(avail_sum, 2) if avail_sum > 0 else None,
                                missing_quantity=req_qty,
                                unit=req_u,
                                status="UNIT_UNCERTAIN",
                            )
                        )
                    elif avail_sum < req_qty:
                        available_required.append(req)
                        deficits.append(
                            IngredientDeficit(
                                ingredient=req,
                                required_quantity=req_qty,
                                available_quantity=round(avail_sum, 2),
                                missing_quantity=round(req_qty - avail_sum, 2),
                                unit=req_u,
                                status="DEFICIT",
                            )
                        )
                    else:
                        available_required.append(req)
                        deficits.append(
                            IngredientDeficit(
                                ingredient=req,
                                required_quantity=req_qty,
                                available_quantity=round(avail_sum, 2),
                                missing_quantity=0.0,
                                unit=req_u,
                                status="AVAILABLE",
                            )
                        )
                else:
                    available_required.append(req)
                    deficits.append(IngredientDeficit(ingredient=req, status="AVAILABLE"))

        optional_available = [
            ingredient for ingredient in optional if _pantry_contains(pantry_names, ingredient)
        ]
        total = len(required) + len(optional)
        required_coverage = 0.0
        for deficit in deficits:
            if deficit.status == "AVAILABLE":
                required_coverage += 1.0
            elif deficit.status == "DEFICIT" and deficit.required_quantity:
                required_coverage += min(
                    1.0, max(0.0, (deficit.available_quantity or 0.0) / deficit.required_quantity)
                )
            elif deficit.status == "UNIT_UNCERTAIN":
                required_coverage += 0.5
        coverage = (required_coverage + len(optional_available)) / max(total, 1)

        raw_complete = template.get("complete_ingredients") or [
            {"name": ing, "quantity": 1, "unit": "unit", "category": "Required"} for ing in required
        ]
        template_nutrients = template.get("nutrients_per_serving")
        nutrients_snapshot = NutrientSnapshot(**template_nutrients) if template_nutrients else None

        recommendations.append(
            RecipeRecommendation(
                recipe_id=str(template["id"]),
                title=str(template["title"]),
                required_ingredients=required,
                available_ingredients=available_required,
                missing_required=missing_required,
                optional_available=optional_available,
                coverage=round(coverage, 3),
                steps=[str(step) for step in template["steps"]],
                source=str(bundle["source"]),
                source_version=str(bundle["schema_version"]),
                method=str(bundle["method"]),
                available_substitutions=_available_substitutions(
                    bundle, missing_required, pantry_names
                ),
                preparation_complexity=_preparation_complexity(required, template["steps"]),
                deficits=deficits,
                servings=servings,
                nutrients_per_serving=nutrients_snapshot,
                total_ingredients_count=len(raw_complete),
                complete_ingredients=raw_complete,
                nutrition_provenance="DETERMINISTIC_INGREDIENT_SUMMATION_V1",
            )
        )

    if mode == "USE_SELECTED_INGREDIENTS" and selected_ingredients:
        norm_sel = [s.casefold().strip() for s in selected_ingredients if s.strip()]
        return sorted(
            recommendations,
            key=lambda item: (
                -sum(
                    1
                    for s in norm_sel
                    if any(
                        s in ing.casefold() or _pantry_contains([s], ing)
                        for ing in item.required_ingredients
                    )
                ),
                -sum(
                    1
                    for s in norm_sel
                    if any(
                        s in ing.casefold() or _pantry_contains([s], ing)
                        for ing in [
                            *item.required_ingredients,
                            *item.available_ingredients,
                            *item.missing_required,
                            *item.optional_available,
                        ]
                    )
                ),
                len(item.missing_required),
                -item.coverage,
                item.title,
            ),
        )

    if mode == "USE_EXPIRING_SOON":
        expiring = [
            item.name.casefold()
            for item in active_pantry
            if item.expires_on is not None and (item.expires_on - today).days <= 3
        ]
        return sorted(
            recommendations,
            key=lambda item: (
                -sum(
                    1
                    for exp in expiring
                    if any(
                        _pantry_contains([exp], ing)
                        for ing in [
                            *item.required_ingredients,
                            *item.available_ingredients,
                            *item.optional_available,
                        ]
                    )
                ),
                len(item.missing_required),
                -item.coverage,
                item.title,
            ),
        )

    if mode == "USE_LEFTOVERS":
        leftovers = [
            item.name.casefold()
            for item in active_pantry
            if item.item_role == "LEFTOVER" or "leftover" in item.name.casefold()
        ]
        return sorted(
            recommendations,
            key=lambda item: (
                -sum(
                    1
                    for lft in leftovers
                    if any(
                        _pantry_contains([lft], ing)
                        for ing in [
                            *item.required_ingredients,
                            *item.available_ingredients,
                            *item.optional_available,
                        ]
                    )
                ),
                len(item.missing_required),
                -item.coverage,
                item.title,
            ),
        )

    if mode == "PLAN_A_RECIPE":
        return sorted(
            recommendations,
            key=lambda item: (
                -sum(
                    1
                    for d in item.deficits
                    if d.required_quantity is not None and d.status in {"DEFICIT", "MISSING"}
                ),
                -sum(1 for d in item.deficits if d.required_quantity is not None),
                -len(item.required_ingredients),
                -item.coverage,
                item.title,
            ),
        )

    return sorted(
        recommendations,
        key=lambda item: (len(item.missing_required), -item.coverage, item.title),
    )


@router.post(
    "/recipes/templates/{template_id}/plan-to-shopping",
    response_model=TemplateRecipePlanResponse,
)
def plan_template_recipe_to_shopping(
    template_id: str,
    payload: TemplateRecipePlanRequest,
    user: Annotated[User, Depends(current_user)],
) -> TemplateRecipePlanResponse:
    bundle = _recipe_bundle()
    template = next((t for t in bundle["templates"] if t["id"] == template_id), None)
    if template is None:
        raise HTTPException(status_code=404, detail="Recipe template not found.")

    pantry_items = product_store.list_pantry(user.id)
    today = datetime.now(UTC).date()
    active_pantry = [
        item for item in pantry_items if item.expires_on is None or item.expires_on >= today
    ]

    details = {d["name"].casefold(): d for d in template.get("ingredient_details", [])}
    required = [str(item) for item in template["required"]]

    current_shopping = product_store.list_shopping_list(user.id)
    existing_by_name = {
        item.name.casefold().strip(): item
        for item in current_shopping
        if not item.checked and item.source == "RECIPE_PLAN"
    }

    additions: list[ShoppingListItem] = []
    planned_items: list[ShoppingListItem] = []
    deficits: list[IngredientDeficit] = []

    for req in required:
        req_norm = req.casefold()
        detail = details.get(req_norm)
        req_qty = float(detail["quantity"]) * payload.servings if detail else payload.servings
        req_unit = str(detail["unit"]) if detail else "unit"

        matching = [item for item in active_pantry if _pantry_contains([item.name.casefold()], req)]

        available_qty = 0.0
        conversion_uncertain = False
        for m in matching:
            conv = _convert_quantity(m.quantity or 0.0, m.unit or "", req_unit)
            if conv is None:
                conversion_uncertain = True
            else:
                available_qty += conv

        status_val: Literal["AVAILABLE", "DEFICIT", "MISSING", "UNIT_UNCERTAIN"]
        if conversion_uncertain and available_qty < req_qty:
            deficit_qty = req_qty
            status_val = "UNIT_UNCERTAIN"
        elif available_qty < req_qty:
            deficit_qty = round(req_qty - available_qty, 2)
            status_val = "DEFICIT" if available_qty > 0 else "MISSING"
        else:
            deficit_qty = 0.0
            status_val = "AVAILABLE"

        deficits.append(
            IngredientDeficit(
                ingredient=req,
                required_quantity=round(req_qty, 2),
                available_quantity=round(available_qty, 2) if not conversion_uncertain else None,
                missing_quantity=round(deficit_qty, 2) if deficit_qty > 0 else None,
                unit=req_unit,
                status=status_val,
            )
        )

        if deficit_qty > 0:
            norm_key = req.casefold().strip()
            existing = existing_by_name.get(norm_key)
            if existing is None:
                new_item = ShoppingListItem(
                    id=str(uuid4()),
                    name=req.capitalize(),
                    checked=False,
                    source="RECIPE_PLAN",
                    quantity=round(deficit_qty, 2),
                    unit=req_unit,
                    recipe_id=template_id,
                )
                additions.append(new_item)
                planned_items.append(new_item)
                existing_by_name[norm_key] = new_item
            else:
                if existing.unit == req_unit and existing.quantity is not None:
                    updated_qty = (
                        round(deficit_qty, 2)
                        if existing.recipe_id == template_id
                        else max(existing.quantity, round(deficit_qty, 2))
                    )
                    updated_item = ShoppingListItem.model_validate(
                        {
                            **existing.model_dump(),
                            "quantity": updated_qty,
                            "source": "RECIPE_PLAN",
                        }
                    )
                    product_store.update_shopping_list_item(user.id, updated_item)
                    planned_items.append(updated_item)
                    existing_by_name[norm_key] = updated_item

    if len(current_shopping) + len(additions) > 200:
        raise HTTPException(status_code=409, detail="Shopping list limit reached.")

    for item in additions:
        product_store.add_shopping_list_item(user.id, item)

    return TemplateRecipePlanResponse(
        template_id=template_id,
        servings=payload.servings,
        generated_count=len(additions),
        items=planned_items,
        deficits=deficits,
    )


class TemplateRecipeDiaryLogRequest(BaseModel):
    servings: float = Field(default=1.0, gt=0, le=100)


@router.post(
    "/recipes/templates/{template_id}/log-to-diary",
    response_model=DiaryEntry,
    status_code=status.HTTP_201_CREATED,
)
def log_template_recipe_to_diary(
    template_id: str,
    payload: TemplateRecipeDiaryLogRequest,
    user: Annotated[User, Depends(current_user)],
) -> DiaryEntry:
    bundle = _recipe_bundle()
    template = next((t for t in bundle["templates"] if t["id"] == template_id), None)
    if template is None:
        raise HTTPException(status_code=404, detail="Recipe template not found.")

    base_nutrients = template.get("nutrients_per_serving")
    scaled_nutrients = (
        _scale_nutrients(NutrientSnapshot.model_validate(base_nutrients), payload.servings)
        if base_nutrients
        else NutrientSnapshot()
    )

    suffix = "s" if payload.servings != 1 else ""
    entry = DiaryEntry(
        id=str(uuid4()),
        name=f"{template['title']} ({payload.servings:g} serving{suffix})",
        eaten_at=datetime.now(UTC),
        serving_grams=None,
        nutrients=scaled_nutrients,
        scan_id=None,
        source="RECIPE",
        recipe_id=template_id,
        recipe_version=1,
        recipe_servings=payload.servings,
    )
    product_store.add_diary(user.id, entry)
    return entry


@router.get("/recipes/use-soon", response_model=UseSoonRecipeResponse)
def use_soon_recipe_suggestions(
    user: Annotated[User, Depends(current_user)],
) -> UseSoonRecipeResponse:
    today = datetime.now(UTC).date()
    attention: list[PantryAttentionItem] = []
    for item in product_store.list_pantry(user.id):
        if item.expires_on is not None and item.expires_on < today:
            continue
        reasons: list[Literal["USER_MARKED_LEFTOVER", "EXPIRES_TODAY", "EXPIRING_SOON"]] = []
        if item.item_role == "LEFTOVER":
            reasons.append("USER_MARKED_LEFTOVER")
        if item.expires_on is not None:
            days = (item.expires_on - today).days
            if days == 0:
                reasons.append("EXPIRES_TODAY")
            elif days <= 3:
                reasons.append("EXPIRING_SOON")
        if reasons:
            attention.append(
                PantryAttentionItem(
                    pantry_item_id=item.id,
                    name=item.name,
                    reasons=reasons,
                )
            )

    suggestions = []
    for recipe in recipe_recommendations(user):
        matched = [
            item
            for item in attention
            if any(
                _pantry_contains([item.name.casefold()], ingredient)
                for ingredient in [
                    *recipe.available_ingredients,
                    *recipe.optional_available,
                ]
            )
        ]
        if matched:
            suggestions.append(UseSoonRecipeSuggestion(recipe=recipe, attention_items=matched))
    return UseSoonRecipeResponse(suggestions=suggestions[:10])


@router.post("/recipes/compare", response_model=RecipeNutritionComparisonResponse)
def compare_recipe_nutrition(
    payload: RecipeNutritionComparisonRequest,
    user: Annotated[User, Depends(current_user)],
) -> RecipeNutritionComparisonResponse:
    del user
    normalized_names = [candidate.name.casefold() for candidate in payload.candidates]
    if len(set(normalized_names)) != len(normalized_names):
        raise HTTPException(status_code=422, detail="Recipe names must be unique.")
    return RecipeNutritionComparisonResponse(
        candidates=[
            RecipeNutritionCandidate(
                **candidate.model_dump(),
                per_serving=_scale_nutrients(candidate.nutrients, 1 / candidate.servings),
            )
            for candidate in payload.candidates
        ],
        compared_nutrients=list(NutrientSnapshot.model_fields),
    )


@router.get("/analytics/summary", response_model=AnalyticsSummary)
def analytics_summary(
    user: Annotated[User, Depends(current_user)],
    days: int = Query(default=30, ge=1, le=3_650),
) -> AnalyticsSummary:
    period_days = min(days, int(_entitlements(user)["analytics.history_days"]))
    cutoff = datetime.now(UTC) - timedelta(days=period_days)
    entries = product_store.list_diary(user.id, cutoff)
    totals = _sum_nutrients(entry.nutrients for entry in entries)
    divisor = max(1, min(period_days, len({item.eaten_at.date() for item in entries})))
    averages = _scale_nutrients(totals, 1 / divisor)
    insights = _analytics_insights(averages, bool(entries))
    goal_tracking_state, goal_progress = _goal_progress(_profile(user.id), averages)
    return AnalyticsSummary(
        period_days=period_days,
        diary_entries=len(entries),
        totals=totals,
        daily_averages=averages,
        insights=insights,
        goal_tracking_state=goal_tracking_state,
        goal_progress=goal_progress,
    )


@router.get("/analytics/trend", response_model=list[AnalyticsTrendPoint])
def analytics_trend(
    user: Annotated[User, Depends(current_user)],
    days: int = 7,
) -> list[AnalyticsTrendPoint]:
    entitlement_days = int(_entitlements(user)["analytics.history_days"])
    period_days = max(1, min(days, entitlement_days, 90))
    today = datetime.now(UTC).date()
    first_day = today - timedelta(days=period_days - 1)
    cutoff = datetime.combine(first_day, datetime.min.time(), tzinfo=UTC)
    entries = product_store.list_diary(user.id, cutoff)
    totals_by_day: dict[date, NutrientSnapshot] = {}
    for entry in entries:
        entry_day = entry.eaten_at.astimezone(UTC).date()
        current = totals_by_day.get(entry_day, _sum_nutrients([]))
        totals_by_day[entry_day] = _sum_nutrients([current, entry.nutrients])
    return [
        AnalyticsTrendPoint(date=day, **totals_by_day.get(day, _sum_nutrients([])).model_dump())
        for day in (first_day + timedelta(days=offset) for offset in range(period_days))
    ]


@router.get("/analytics/compare", response_model=AnalyticsComparisonResponse)
def compare_analytics_periods(
    user: Annotated[User, Depends(current_user)],
    days: int = Query(default=7, ge=1, le=90),
) -> AnalyticsComparisonResponse:
    period_days = min(days, int(_entitlements(user)["analytics.history_days"]))
    today = datetime.now(UTC).date()
    current_first = today - timedelta(days=period_days - 1)
    previous_last = current_first - timedelta(days=1)
    previous_first = previous_last - timedelta(days=period_days - 1)
    cutoff = datetime.combine(previous_first, datetime.min.time(), tzinfo=UTC)
    entries = product_store.list_diary(user.id, cutoff)
    current_entries = [
        entry
        for entry in entries
        if current_first <= entry.eaten_at.astimezone(UTC).date() <= today
    ]
    previous_entries = [
        entry
        for entry in entries
        if previous_first <= entry.eaten_at.astimezone(UTC).date() <= previous_last
    ]
    current = _analytics_period_snapshot(current_first, today, current_entries)
    previous = _analytics_period_snapshot(previous_first, previous_last, previous_entries)
    state: Literal["AVAILABLE", "INSUFFICIENT_HISTORY"] = (
        "AVAILABLE"
        if current.logged_days > 0 and previous.logged_days > 0
        else "INSUFFICIENT_HISTORY"
    )
    changes = (
        _analytics_metric_changes(current.daily_averages, previous.daily_averages)
        if state == "AVAILABLE"
        else []
    )
    stories = [
        AnalyticsStory(
            kind="PERIOD_COVERAGE",
            title="Logged-day coverage",
            evidence=(
                f"Current window has {current.logged_days} logged day(s); the adjacent previous "
                f"window has {previous.logged_days}."
            ),
            supporting_records=current.diary_entries + previous.diary_entries,
        )
    ]
    stories.extend(
        AnalyticsStory(
            kind="RECORDED_AVERAGE_CHANGE",
            title=f"{change.label} recorded average",
            evidence=_analytics_change_story(change),
            supporting_records=current.diary_entries + previous.diary_entries,
        )
        for change in changes
    )
    return AnalyticsComparisonResponse(
        state=state,
        period_days=period_days,
        current=current,
        previous=previous,
        changes=changes,
        stories=stories,
    )


@router.get("/analytics/drilldown", response_model=AnalyticsDrilldownResponse)
def analytics_drilldown(
    user: Annotated[User, Depends(current_user)],
    days: int = Query(default=30, ge=1, le=3_650),
    selected_date: Annotated[date | None, Query(alias="date")] = None,
    limit: int = Query(default=100, ge=1, le=200),
) -> AnalyticsDrilldownResponse:
    period_days = min(days, int(_entitlements(user)["analytics.history_days"]))
    today = datetime.now(UTC).date()
    first_day = today - timedelta(days=period_days - 1)
    cutoff = datetime.combine(first_day, datetime.min.time(), tzinfo=UTC)
    entries = product_store.list_diary(user.id, cutoff)
    if selected_date is not None:
        if selected_date < first_day or selected_date > today:
            entries = []
        else:
            entries = [
                entry for entry in entries if entry.eaten_at.astimezone(UTC).date() == selected_date
            ]
    return AnalyticsDrilldownResponse(
        period_days=period_days,
        selected_date=selected_date,
        entries=entries[:limit],
    )


@router.get("/analytics/patterns", response_model=DietaryPatternResponse)
def dietary_patterns(
    user: Annotated[User, Depends(current_user)],
    days: int = Query(default=90, ge=7, le=3_650),
) -> DietaryPatternResponse:
    period_days = min(days, int(_entitlements(user)["analytics.history_days"]))
    today = datetime.now(UTC).date()
    first_day = today - timedelta(days=period_days - 1)
    cutoff = datetime.combine(first_day, datetime.min.time(), tzinfo=UTC)
    entries = product_store.list_diary(user.id, cutoff)
    entries_by_day: dict[date, list[DiaryEntry]] = {}
    for entry in entries:
        entries_by_day.setdefault(entry.eaten_at.astimezone(UTC).date(), []).append(entry)
    observed_days = len(entries_by_day)
    if observed_days < 7:
        return DietaryPatternResponse(
            period_days=period_days,
            state="INSUFFICIENT_HISTORY",
            observed_days=observed_days,
            observations=[],
        )

    observations = [
        DietaryPatternObservation(
            kind="LOGGING_COVERAGE",
            label="Logged-day coverage",
            evidence=(
                f"Diary entries were recorded on {observed_days} of {period_days} days "
                f"({round(observed_days / period_days * 100)}%)."
            ),
            supporting_records=len(entries),
        )
    ]
    normalized_names = Counter(entry.name.strip().casefold() for entry in entries)
    display_names = {entry.name.strip().casefold(): entry.name.strip() for entry in entries}
    for normalized_name, count in normalized_names.most_common(3):
        if count < 2:
            continue
        observations.append(
            DietaryPatternObservation(
                kind="RECURRING_ENTRY",
                label=f"Recurring entry: {display_names[normalized_name]}",
                evidence=f"This diary name appears in {count} records in the selected window.",
                supporting_records=count,
            )
        )

    timing_counts: Counter[str] = Counter()
    for entry in entries:
        hour = entry.eaten_at.astimezone(UTC).hour
        bucket = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
        timing_counts[bucket] += 1
    timing_label, timing_count = timing_counts.most_common(1)[0]
    observations.append(
        DietaryPatternObservation(
            kind="MEAL_TIMING",
            label=f"Most recorded UTC period: {timing_label}",
            evidence=f"{timing_count} of {len(entries)} records were logged in this UTC period.",
            supporting_records=timing_count,
        )
    )

    daily_calories = [
        value
        for day_entries in entries_by_day.values()
        if (value := _sum_nutrients(entry.nutrients for entry in day_entries).calories) is not None
    ]
    if len(daily_calories) == observed_days:
        observations.append(
            DietaryPatternObservation(
                kind="NUTRIENT_RANGE",
                label="Logged daily energy range",
                evidence=(
                    f"Recorded daily energy ranged from {round(min(daily_calories))} to "
                    f"{round(max(daily_calories))} kcal across logged days."
                ),
                supporting_records=observed_days,
            )
        )
    return DietaryPatternResponse(
        period_days=period_days,
        state="AVAILABLE",
        observed_days=observed_days,
        observations=observations,
    )


@router.get("/analytics/export.csv")
def export_analytics_csv(user: Annotated[User, Depends(current_user)]) -> Response:
    history_days = int(_entitlements(user)["analytics.history_days"])
    cutoff = datetime.now(UTC) - timedelta(days=history_days)
    entries = product_store.list_diary(user.id, cutoff)
    output = StringIO(newline="")
    csv_writer = csv.writer(output, lineterminator="\n")
    csv_writer.writerow(
        [
            "eaten_at",
            "name",
            "serving_grams",
            "calories",
            "protein_g",
            "carbs_g",
            "fat_g",
            "sugar_g",
            "sodium_mg",
            "fiber_g",
            "vitamin_a_mcg",
            "vitamin_c_mg",
            "vitamin_d_mcg",
            "calcium_mg",
            "iron_mg",
            "potassium_mg",
            "zinc_mg",
        ]
    )
    for entry in entries:
        csv_writer.writerow(
            [
                entry.eaten_at.isoformat(),
                _spreadsheet_safe(entry.name),
                entry.serving_grams,
                entry.nutrients.calories,
                entry.nutrients.protein_g,
                entry.nutrients.carbs_g,
                entry.nutrients.fat_g,
                entry.nutrients.sugar_g,
                entry.nutrients.sodium_mg,
                entry.nutrients.fiber_g,
                entry.nutrients.vitamin_a_mcg,
                entry.nutrients.vitamin_c_mg,
                entry.nutrients.vitamin_d_mcg,
                entry.nutrients.calcium_mg,
                entry.nutrients.iron_mg,
                entry.nutrients.potassium_mg,
                entry.nutrients.zinc_mg,
            ]
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="nutrilens-diary.csv"'},
    )


@router.get("/recommendations/scans/{scan_id}", response_model=RecommendationResponse)
def scan_recommendations(
    scan_id: str, user: Annotated[User, Depends(current_user)]
) -> RecommendationResponse:
    try:
        scan = get_owned_scan_result(scan_id, user)
    except ScanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Scan not found.") from exc
    intelligence = get_r4_service().analyze(scan.ingredients, scan.nutrition)
    profile = _profile(user.id)
    findings: list[PersonalizedFinding] = []
    if not profile.consent_personalization:
        return RecommendationResponse(
            scan_id=scan_id,
            findings=[
                PersonalizedFinding(
                    level="INFO",
                    title="Personalization is off",
                    explanation=(
                        "NutriLens did not use your saved goals, allergens, or preferences. "
                        "Enable consent in Account if you want profile-aware findings."
                    ),
                )
            ],
            advanced=False,
            profile_used=False,
            personalization_state="DISABLED_NO_CONSENT",
        )
    detected_allergens = {
        item.allergen.canonical_name.casefold()
        for item in intelligence.allergens
        if item.allergen.matched and item.allergen.canonical_name
    }
    conflicts = detected_allergens & {item.casefold() for item in profile.allergens}
    if conflicts:
        findings.append(
            PersonalizedFinding(
                level="SAFETY",
                title="Declared allergen conflict",
                explanation=(
                    "A governed allergen match overlaps your declared profile. "
                    "Verify the physical label before eating."
                ),
                evidence=sorted(conflicts),
            )
        )
    if profile.goal == "low-sugar" and intelligence.hidden_sugars.signals:
        findings.append(
            PersonalizedFinding(
                level="CAUTION",
                title="Recognized sugar sources",
                explanation="This may be less suitable for your stated low-sugar preference.",
                evidence=[item.ingredient_text for item in intelligence.hidden_sugars.signals],
            )
        )
    if profile.goal == "low-sodium" and intelligence.sodium_sources.signals:
        findings.append(
            PersonalizedFinding(
                level="CAUTION",
                title="Recognized sodium sources",
                explanation="This may be less suitable for your stated low-sodium preference.",
                evidence=[item.ingredient_text for item in intelligence.sodium_sources.signals],
            )
        )
    # Dietary style check
    non_veg_keywords = {
        "chicken",
        "beef",
        "pork",
        "meat",
        "mutton",
        "fish",
        "gelatin",
        "gelatine",
        "prawn",
        "crab",
    }
    egg_keywords = {"egg", "albumin", "ovalbumin"}
    dairy_keywords = {"milk", "butter", "cheese", "paneer", "whey", "casein", "curd", "ghee"}
    raw_ingredients_text = (scan.ingredients.raw_text if scan.ingredients else "").lower()

    if profile.dietary_style == "Vegetarian" and any(
        k in raw_ingredients_text for k in non_veg_keywords
    ):
        findings.append(
            PersonalizedFinding(
                level="SAFETY",
                title="Dietary style conflict: Non-vegetarian ingredient observed",
                explanation=(
                    "Observed ingredient evidence conflicts with your Vegetarian diet preference."
                ),
                evidence=[k for k in non_veg_keywords if k in raw_ingredients_text],
            )
        )
    elif profile.dietary_style == "Vegan" and any(
        k in raw_ingredients_text for k in (non_veg_keywords | egg_keywords | dairy_keywords)
    ):
        findings.append(
            PersonalizedFinding(
                level="SAFETY",
                title="Dietary style conflict: Animal product observed",
                explanation=(
                    "Observed ingredient evidence conflicts with your Vegan dietary preference."
                ),
                evidence=[
                    k
                    for k in (non_veg_keywords | egg_keywords | dairy_keywords)
                    if k in raw_ingredients_text
                ],
            )
        )

    # Health conditions and intolerance checks (density-aware)
    observed_sodium_per_100: float | None = None
    observed_sodium_per_serving: float | None = None
    observed_sugar_per_100: float | None = None
    observed_sugar_per_serving: float | None = None

    if scan.nutrition and scan.nutrition.table_rows:
        per_100_vals, per_serv_vals = _extract_food_nutrients(scan.nutrition)
        observed_sodium_per_100 = per_100_vals.sodium_mg
        observed_sodium_per_serving = per_serv_vals.sodium_mg
        observed_sugar_per_100 = per_100_vals.sugar_g
        observed_sugar_per_serving = per_serv_vals.sugar_g

    has_bp_cond = (
        "Hypertension" in profile.health_conditions or "Heart health" in profile.health_conditions
    )
    if has_bp_cond:
        # Density-aware thresholds: >400 mg / serving OR >1000 mg / 100g
        is_high_sodium = False
        sodium_ev = []
        if observed_sodium_per_serving is not None and observed_sodium_per_serving > 400.0:
            is_high_sodium = True
            sodium_ev.append(f"Sodium: {observed_sodium_per_serving:.0f} mg/serving")
        elif observed_sodium_per_100 is not None and observed_sodium_per_100 > 1000.0:
            is_high_sodium = True
            sodium_ev.append(f"Sodium: {observed_sodium_per_100:.0f} mg/100g")

        if is_high_sodium:
            findings.append(
                PersonalizedFinding(
                    level="CAUTION",
                    title="Condition guidance: High sodium observed",
                    explanation=(
                        f"Structured label reports {' and '.join(sodium_ev)}, "
                        "which warrants caution for blood pressure management."
                    ),
                    evidence=sodium_ev,
                )
            )
        elif intelligence.sodium_sources.signals:
            findings.append(
                PersonalizedFinding(
                    level="CAUTION",
                    title="Condition guidance: Sodium sources observed",
                    explanation=(
                        "Observed sodium or salt sources may warrant caution for blood "
                        "pressure management."
                    ),
                    evidence=[item.ingredient_text for item in intelligence.sodium_sources.signals],
                )
            )

    has_sugar_cond = "Diabetes" in profile.health_conditions or "PCOS" in profile.health_conditions
    if has_sugar_cond:
        # Density-aware thresholds: >10 g / serving OR >20 g / 100g
        is_high_sugar = False
        sugar_ev = []
        if observed_sugar_per_serving is not None and observed_sugar_per_serving > 10.0:
            is_high_sugar = True
            sugar_ev.append(f"Sugar: {observed_sugar_per_serving:.1f} g/serving")
        elif observed_sugar_per_100 is not None and observed_sugar_per_100 > 20.0:
            is_high_sugar = True
            sugar_ev.append(f"Sugar: {observed_sugar_per_100:.1f} g/100g")

        if is_high_sugar:
            findings.append(
                PersonalizedFinding(
                    level="CAUTION",
                    title="Condition guidance: High sugar observed",
                    explanation=(
                        f"Structured label reports {' and '.join(sugar_ev)}, "
                        "which warrants caution for blood glucose management."
                    ),
                    evidence=sugar_ev,
                )
            )
        elif intelligence.hidden_sugars.signals:
            findings.append(
                PersonalizedFinding(
                    level="CAUTION",
                    title="Condition guidance: Sugar sources observed",
                    explanation=(
                        "Observed sugar or high-glycemic sweetener sources may warrant "
                        "caution for blood glucose management."
                    ),
                    evidence=[item.ingredient_text for item in intelligence.hidden_sugars.signals],
                )
            )

    has_lactose_intolerance = any(
        "lactose" in s.casefold() or "dairy" in s.casefold()
        for s in profile.intolerances + profile.allergens + profile.health_conditions
    )
    if has_lactose_intolerance and any(k in raw_ingredients_text for k in dairy_keywords):
        findings.append(
            PersonalizedFinding(
                level="SAFETY",
                title="Condition conflict: Dairy/lactose ingredients observed",
                explanation=(
                    "Observed ingredient evidence conflicts with your declared lactose "
                    "intolerance/dairy allergy."
                ),
                evidence=[k for k in dairy_keywords if k in raw_ingredients_text],
            )
        )

    # Calculate Fit Score
    safety_conflicts = sum(1 for f in findings if f.level == "SAFETY")
    caution_signals = sum(1 for f in findings if f.level == "CAUTION")
    has_nutrition = scan.nutrition is not None and bool(scan.nutrition.table_rows)
    has_ingredients = scan.ingredients is not None and bool(scan.ingredients.raw_text.strip())

    if not has_nutrition or not has_ingredients:
        if safety_conflicts > 0:
            fit_score = PersonalFitScore(
                score=25,
                category="POOR_FIT",
                label="Poor fit · Safety/dietary conflict",
                reasons=[f.explanation for f in findings if f.level == "SAFETY"],
                evidence_sufficiency="PARTIAL",
            )
        elif not has_nutrition and not has_ingredients:
            fit_score = PersonalFitScore(
                score=None,
                category="NOT_ENOUGH_EVIDENCE",
                label="Not enough evidence",
                reasons=[
                    "Scan did not yield sufficient structured nutrition or ingredient evidence "
                    "to evaluate personal fit."
                ],
                evidence_sufficiency="INSUFFICIENT",
            )
        elif caution_signals > 0:
            fit_score = PersonalFitScore(
                score=65,
                category="MODERATE_FIT",
                label="Moderate fit · Partial evidence",
                reasons=[f.explanation for f in findings if f.level == "CAUTION"],
                evidence_sufficiency="PARTIAL",
            )
        else:
            fit_score = PersonalFitScore(
                score=None,
                category="NOT_ENOUGH_EVIDENCE",
                label="Not enough evidence",
                reasons=[
                    "Label requires both verified nutrition facts and ingredients list "
                    "for complete fit evaluation."
                ],
                evidence_sufficiency="PARTIAL",
            )
    elif safety_conflicts > 0:
        fit_score = PersonalFitScore(
            score=25,
            category="POOR_FIT",
            label="Poor fit · Safety/dietary conflict",
            reasons=[f.explanation for f in findings if f.level == "SAFETY"],
            evidence_sufficiency="SUFFICIENT",
        )
    elif caution_signals > 1:
        fit_score = PersonalFitScore(
            score=60,
            category="MODERATE_FIT",
            label="Moderate fit · Watch ingredients",
            reasons=[f.explanation for f in findings if f.level == "CAUTION"],
            evidence_sufficiency="SUFFICIENT",
        )
    elif caution_signals == 1:
        fit_score = PersonalFitScore(
            score=78,
            category="GOOD_FIT",
            label="Good fit · Minor watchpoints",
            reasons=[f.explanation for f in findings if f.level == "CAUTION"],
            evidence_sufficiency="SUFFICIENT",
        )
    else:
        fit_score = PersonalFitScore(
            score=92,
            category="GREAT_FIT",
            label="Great fit · Aligned with your profile",
            reasons=[
                "No allergen, dietary style, or condition conflicts identified "
                "in observed evidence."
            ],
            evidence_sufficiency="SUFFICIENT",
        )

    # Suggest better alternatives based on specific conflict reasons and user profile
    better_alternatives: list[BetterAlternative] = []
    if fit_score.category in ("POOR_FIT", "MODERATE_FIT"):
        # Catalogue of approved alternatives with nutrition profiles
        canonical_alternatives = [
            BetterAlternative(
                name="Plain Rolled Whole Oats",
                category="Breakfast & Cereals",
                why_better="Zero added sugar, 100% whole grain, naturally low sodium.",
                key_nutrition_advantage="High soluble fiber (beta-glucan), no refined additives.",
                dietary_compatibility=["Vegetarian", "Vegan", "Heart health", "Diabetes"],
            ),
            BetterAlternative(
                name="Organic Unsweetened Greek Yogurt",
                category="Dairy & High Protein",
                why_better="High natural protein without added sugars or thickeners.",
                key_nutrition_advantage="15g protein per 100g, active probiotic cultures.",
                dietary_compatibility=["Vegetarian", "Keto", "High protein"],
            ),
            BetterAlternative(
                name="Organic Roasted Chickpeas (Salt-Free)",
                category="Snacks & Savories",
                why_better="Naturally high fiber and protein with zero sodium.",
                key_nutrition_advantage="0mg sodium, 12g protein per 100g, low glycemic impact.",
                dietary_compatibility=[
                    "Vegetarian",
                    "Vegan",
                    "Hypertension",
                    "Heart health",
                    "Diabetes",
                ],
            ),
            BetterAlternative(
                name="Fortified Unsweetened Soya Milk",
                category="Plant Dairy & Beverages",
                why_better="Dairy-free and lactose-free complete plant protein.",
                key_nutrition_advantage=(
                    "7g plant protein per serving, fortified with calcium and B12."
                ),
                dietary_compatibility=["Vegan", "Vegetarian", "Lactose intolerant", "Diabetes"],
            ),
        ]

        # Filter out alternatives that conflict with ANY declared profile allergens,
        # intolerances, or food exclusions
        all_user_exclusions = {
            s.casefold().strip()
            for s in (profile.allergens + profile.intolerances + profile.food_exclusions)
            if s.strip()
        }

        for alt in canonical_alternatives:
            alt_name_lower = alt.name.casefold()
            alt_cat_lower = alt.category.casefold()

            # Check dietary style compatibility
            if profile.dietary_style == "Vegan" and "Vegan" not in alt.dietary_compatibility:
                continue
            if (
                profile.dietary_style == "Vegetarian"
                and "Vegetarian" not in alt.dietary_compatibility
            ):
                continue

            # Check generic exclusions against name and category
            has_exclusion_conflict = False
            for exclusion_term in all_user_exclusions:
                if exclusion_term in alt_name_lower or exclusion_term in alt_cat_lower:
                    has_exclusion_conflict = True
                    break
                if exclusion_term in {"dairy", "milk", "lactose"} and "dairy" in alt_cat_lower:
                    has_exclusion_conflict = True
                    break
                if exclusion_term in {"soy", "soya"} and (
                    "soy" in alt_name_lower or "soya" in alt_name_lower
                ):
                    has_exclusion_conflict = True
                    break
                if exclusion_term in {"oat", "oats"} and (
                    "oat" in alt_name_lower or "oats" in alt_name_lower
                ):
                    has_exclusion_conflict = True
                    break
                if (
                    exclusion_term in {"chickpea", "chickpeas", "legume", "legumes"}
                    and "chickpea" in alt_name_lower
                ):
                    has_exclusion_conflict = True
                    break

            if has_exclusion_conflict:
                continue

            # Prioritize alternative addressing specific condition or reason
            matches_condition = any(
                cond in alt.dietary_compatibility for cond in profile.health_conditions
            )
            has_sodium_conflict = any("sodium" in f.title.casefold() for f in findings)
            has_sugar_conflict = any("sugar" in f.title.casefold() for f in findings)

            should_prioritize = (
                has_sodium_conflict and "Hypertension" in alt.dietary_compatibility
            ) or (has_sugar_conflict and "Diabetes" in alt.dietary_compatibility)
            if should_prioritize:
                better_alternatives.insert(0, alt)
            elif matches_condition or not profile.health_conditions:
                better_alternatives.append(alt)

        # Deduplicate while preserving rank
        seen_names = set()
        deduped_alts: list[BetterAlternative] = []
        for alt in better_alternatives:
            if alt.name not in seen_names:
                seen_names.add(alt.name)
                deduped_alts.append(alt)
        better_alternatives = deduped_alts[:3]

    if not findings:
        findings.append(
            PersonalizedFinding(
                level="INFO",
                title="No declared-profile conflict detected",
                explanation=(
                    "Available evidence did not identify a priority conflict. "
                    "This is not a guarantee of safety."
                ),
            )
        )
    return RecommendationResponse(
        scan_id=scan_id,
        findings=findings,
        advanced=bool(_entitlements(user)["recommendations.advanced"]),
        profile_used=True,
        personalization_state="ENABLED",
        fit_score=fit_score,
        better_alternatives=better_alternatives,
    )


@router.get(
    "/recommendations/scans/{scan_id}/counterfactuals",
    response_model=CounterfactualExplanationResponse,
)
def scan_counterfactuals(
    scan_id: str, user: Annotated[User, Depends(current_user)]
) -> CounterfactualExplanationResponse:
    """Explain how observed signal counts change under bounded evidence ablation."""
    try:
        scan = get_owned_scan_result(scan_id, user)
    except ScanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Scan not found.") from exc
    intelligence = get_r4_service().analyze(scan.ingredients, scan.nutrition)
    categories = (
        ("hidden-sugars", "Recognized sugar-source signals", intelligence.hidden_sugars.signals),
        ("sodium-sources", "Recognized sodium-source signals", intelligence.sodium_sources.signals),
        ("sweeteners", "Recognized sweetener signals", intelligence.sweeteners.signals),
        ("preservatives", "Recognized preservative signals", intelligence.preservatives.signals),
        ("oils-and-fats", "Recognized oil and fat signals", intelligence.oils_and_fats.signals),
    )
    factors: list[ObservedSignalCounterfactual] = []
    for factor_id, label, signals in categories:
        evidence = list(dict.fromkeys(item.ingredient_text for item in signals))
        if not evidence:
            continue
        count = len(evidence)
        factors.append(
            ObservedSignalCounterfactual(
                factor_id=factor_id,
                label=label,
                observed_evidence=evidence,
                hypothesis=(
                    f"If these {label.lower()} were absent from the available label evidence..."
                ),
                result_change=(
                    f"The displayed {label.lower()} count would change from {count} to 0. "
                    "No other result is inferred."
                ),
            )
        )
    return CounterfactualExplanationResponse(
        scan_id=scan_id,
        state="AVAILABLE" if factors else "NO_OBSERVED_SIGNALS",
        factors=factors,
    )


def _extract_food_nutrients(
    nutrition: Any,
) -> tuple[FoodNutrientValues, FoodNutrientValues]:
    """Extract and normalize per-100 and per-serving nutrient values safely."""
    per_100: dict[str, float] = {}
    per_serving: dict[str, float] = {}

    label_map = {
        "energy": "energy_kcal",
        "calories": "energy_kcal",
        "protein": "protein_g",
        "carbohydrate": "carbohydrate_g",
        "carbohydrates": "carbohydrate_g",
        "total_carbohydrate": "carbohydrate_g",
        "carbs": "carbohydrate_g",
        "sugar": "sugar_g",
        "sugars": "sugar_g",
        "total_sugar": "sugar_g",
        "total_sugars": "sugar_g",
        "added_sugar": "added_sugar_g",
        "added_sugars": "added_sugar_g",
        "fat": "fat_g",
        "total_fat": "fat_g",
        "fiber": "fiber_g",
        "dietary_fiber": "fiber_g",
        "sodium": "sodium_mg",
    }

    def _parse_num(val: Any) -> float | None:
        if val is None:
            return None
        text = str(val).strip()
        cleaned = text.replace("<", "").replace(">", "").replace("~", "").strip()
        match = re.match(r"^([0-9]+(?:\.[0-9]+)?)", cleaned)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None

    if hasattr(nutrition, "table_rows"):
        for row in nutrition.table_rows:
            canonical = (
                (getattr(row, "canonical_label", None) or getattr(row, "label", None) or "")
                .strip()
                .lower()
            )
            key = label_map.get(canonical)
            if not key:
                for k, mapped in label_map.items():
                    if k in canonical:
                        key = mapped
                        break
            if not key:
                continue

            parsed_values = getattr(row, "parsed_values", [])
            for pv in parsed_values:
                val_num = _parse_num(getattr(pv, "value", None))
                basis_val = getattr(pv, "basis", "UNKNOWN")
                if val_num is not None:
                    if basis_val in ("PER_100_G", "PER_100_ML"):
                        per_100[key] = val_num
                    elif basis_val == "PER_SERVING":
                        per_serving[key] = val_num

            # Check legacy values if not resolved
            raw_values = getattr(row, "values", [])
            if key not in per_100 and key not in per_serving and raw_values:
                val_num = _parse_num(raw_values[0])
                if val_num is not None:
                    basis_type = getattr(nutrition, "basis", "UNKNOWN")
                    if basis_type in ("PER_100_G", "PER_100_ML"):
                        per_100[key] = val_num
                    elif basis_type == "PER_SERVING":
                        per_serving[key] = val_num
                if len(raw_values) >= 2:
                    val2_num = _parse_num(raw_values[1])
                    if val2_num is not None:
                        basis_type = getattr(nutrition, "basis", "UNKNOWN")
                        if basis_type in ("PER_100_G", "PER_100_ML"):
                            per_serving[key] = val2_num
                        elif basis_type == "PER_SERVING":
                            per_100[key] = val2_num

        serving_val = _parse_num(getattr(nutrition, "serving_size_value", None))
        if serving_val and serving_val > 0:
            for k in label_map.values():
                if k in per_100 and k not in per_serving:
                    per_serving[k] = round(per_100[k] * serving_val / 100.0, 2)
                elif k in per_serving and k not in per_100:
                    per_100[k] = round(per_serving[k] * 100.0 / serving_val, 2)

    return (
        FoodNutrientValues(**per_100),
        FoodNutrientValues(**per_serving),
    )


@router.post("/recommendations/compare", response_model=ComparisonResponse)
def compare_scans(
    payload: ComparisonRequest,
    user: Annotated[User, Depends(current_user)],
) -> ComparisonResponse:
    if len(set(payload.scan_ids)) != len(payload.scan_ids):
        raise HTTPException(status_code=422, detail="Choose distinct scans to compare.")
    profile = _profile(user.id)
    profile_used = profile.consent_personalization
    scored: list[
        tuple[
            int,
            str,
            str,
            dict[str, int],
            list[str],
            list[str],
            str | None,
            str | None,
            str | None,
            FoodNutrientValues,
            FoodNutrientValues,
            list[str],
        ]
    ] = []
    for scan_id in payload.scan_ids:
        try:
            scan = get_owned_scan_result(scan_id, user)
        except ScanNotFoundError as exc:
            raise HTTPException(status_code=404, detail="A selected scan was not found.") from exc
        intelligence = get_r4_service().analyze(scan.ingredients, scan.nutrition)
        counts = {
            "hidden_sugars": len(intelligence.hidden_sugars.signals),
            "sodium_sources": len(intelligence.sodium_sources.signals),
            "sweeteners": len(intelligence.sweeteners.signals),
            "preservatives": len(intelligence.preservatives.signals),
            "oils_and_fats": len(intelligence.oils_and_fats.signals),
            "unresolved_ingredients": intelligence.complexity.unresolved_count,
        }
        burden = sum(counts.values())
        evidence: list[str] = []
        limitations: list[str] = []
        nutrients_100, nutrients_srv = _extract_food_nutrients(scan.nutrition)
        if profile_used and profile.goal == "low-sugar":
            burden += counts["hidden_sugars"] * 2
            evidence.append("Applied the saved lower-sugar preference.")
        elif profile_used and profile.goal == "low-sodium":
            burden += counts["sodium_sources"] * 2
            evidence.append("Applied the saved lower-sodium preference.")
        elif profile_used and profile.goal == "high-protein":
            if nutrients_srv.protein_g is not None:
                evidence.append(f"Protein per serving: {nutrients_srv.protein_g} g.")
            else:
                limitations.append(
                    "Protein ranking is unknown because normalized serving-level protein "
                    "evidence is unavailable."
                )
        detected_allergens = {
            item.allergen.canonical_name.casefold()
            for item in intelligence.allergens
            if item.allergen.matched and item.allergen.canonical_name
        }
        conflicts = (
            detected_allergens & {item.casefold() for item in profile.allergens}
            if profile_used
            else set()
        )
        if conflicts:
            burden += 100
            evidence.append(f"Declared allergen overlap: {', '.join(sorted(conflicts))}.")
        evidence.extend(
            f"{name.replace('_', ' ')}: {count}" for name, count in counts.items() if count
        )
        if intelligence.confidence.state != "HIGH":
            limitations.append(
                f"Ingredient-intelligence confidence is {intelligence.confidence.state.lower()}."
            )
        product_name = (
            scan.product_name_candidates[0].value
            if getattr(scan, "product_name_candidates", None)
            else f"Scan {scan_id[:8]}"
        )
        brand_candidates = getattr(scan, "brand_candidates", None)
        brand_name = (
            brand_candidates[0].value
            if brand_candidates and hasattr(brand_candidates[0], "value")
            else None
        )
        serving_str = None
        if getattr(scan.nutrition, "serving_size_value", None):
            unit = getattr(scan.nutrition, "serving_size_unit", "") or ""
            serving_str = f"{scan.nutrition.serving_size_value} {unit}".strip()
        candidate_allergens = sorted(
            {
                item.allergen.canonical_name
                for item in intelligence.allergens
                if item.allergen.matched and item.allergen.canonical_name
            }
        )
        allergen_text = getattr(scan.ingredients, "allergen_text", "")
        if not candidate_allergens and allergen_text:
            candidate_allergens = [allergen_text]

        scored.append(
            (
                burden,
                scan_id,
                product_name,
                counts,
                evidence,
                limitations,
                brand_name,
                serving_str,
                scan.nutrition.basis,
                nutrients_100,
                nutrients_srv,
                candidate_allergens,
            )
        )
    scored.sort(key=lambda item: (item[0], item[2].casefold(), item[1]))
    candidates = [
        ComparisonCandidate(
            scan_id=scan_id,
            product_name=product_name,
            rank=index + 1,
            signal_burden=burden,
            signal_counts=counts,
            evidence=evidence,
            limitations=limitations,
            brand_name=brand_name,
            serving_size=serving_str,
            basis=basis,
            nutrients_per_100=nutrients_100,
            nutrients_per_serving=nutrients_srv,
            allergens=candidate_allergens,
        )
        for index, (
            burden,
            scan_id,
            product_name,
            counts,
            evidence,
            limitations,
            brand_name,
            serving_str,
            basis,
            nutrients_100,
            nutrients_srv,
            candidate_allergens,
        ) in enumerate(scored)
    ]

    # Check basis alignment across candidates
    unique_bases = {c.basis for c in candidates if c.basis}
    has_unaligned_bases = False
    if len(unique_bases) > 1:
        has_common_100 = all(
            any(
                getattr(c.nutrients_per_100, k, None) is not None
                for k in ("energy_kcal", "protein_g", "sugar_g", "fat_g")
            )
            for c in candidates
        )
        has_common_srv = all(
            any(
                getattr(c.nutrients_per_serving, k, None) is not None
                for k in ("energy_kcal", "protein_g", "sugar_g", "fat_g")
            )
            for c in candidates
        )
        if not has_common_100 and not has_common_srv:
            has_unaligned_bases = True
            for c in candidates:
                c.limitations.append(
                    "Direct nutrient comparison is limited because products use different basis "
                    "declarations without common-basis conversion equivalence."
                )

    recommended_scan_id: str | None = None
    supported_explicit_goals = {"low-sugar", "low-sodium", "high-protein"}

    # Neutral comparison by default: require explicit supported goal and aligned bases
    if (
        profile_used
        and profile.goal in supported_explicit_goals
        and not has_unaligned_bases
        and len(candidates) > 1
    ):
        goal = profile.goal
        if goal == "low-sugar":
            sugar_values = [
                c.nutrients_per_100.sugar_g
                if c.nutrients_per_100.sugar_g is not None
                else c.nutrients_per_serving.sugar_g
                for c in candidates
            ]
            if all(v is not None for v in sugar_values):
                valid_sugars = [v for v in sugar_values if v is not None]
                min_sugar = min(valid_sugars)
                sugar_winners = [
                    c for c, v in zip(candidates, sugar_values, strict=False) if v == min_sugar
                ]
                if len(sugar_winners) == 1:
                    recommended_scan_id = sugar_winners[0].scan_id
            elif candidates[0].signal_burden < candidates[1].signal_burden:
                recommended_scan_id = candidates[0].scan_id
        elif goal == "low-sodium":
            sodium_values = [
                c.nutrients_per_100.sodium_mg
                if c.nutrients_per_100.sodium_mg is not None
                else c.nutrients_per_serving.sodium_mg
                for c in candidates
            ]
            if all(v is not None for v in sodium_values):
                valid_sodiums = [v for v in sodium_values if v is not None]
                min_sodium = min(valid_sodiums)
                sodium_winners = [
                    c for c, v in zip(candidates, sodium_values, strict=False) if v == min_sodium
                ]
                if len(sodium_winners) == 1:
                    recommended_scan_id = sodium_winners[0].scan_id
            elif candidates[0].signal_burden < candidates[1].signal_burden:
                recommended_scan_id = candidates[0].scan_id
        elif goal == "high-protein":
            protein_values = [
                c.nutrients_per_100.protein_g
                if c.nutrients_per_100.protein_g is not None
                else c.nutrients_per_serving.protein_g
                for c in candidates
            ]
            if all(v is not None for v in protein_values):
                valid_proteins = [v for v in protein_values if v is not None]
                max_protein = max(valid_proteins)
                protein_winners = [
                    c for c, v in zip(candidates, protein_values, strict=False) if v == max_protein
                ]
                if len(protein_winners) == 1:
                    recommended_scan_id = protein_winners[0].scan_id
            else:
                for c in candidates:
                    c.limitations.append(
                        "Protein ranking cannot be determined because protein evidence is missing "
                        "or unaligned; unknown values cannot be assumed zero."
                    )
    else:
        # Neutral comparison by default: no recommended_scan_id without explicit supported goal
        recommended_scan_id = None

    return ComparisonResponse(
        candidates=candidates,
        recommended_scan_id=recommended_scan_id,
        profile_used=profile_used,
    )


@router.get("/recommendations/similar/{scan_id}", response_model=SimilarProductResponse)
def similar_products(
    scan_id: str,
    user: Annotated[User, Depends(current_user)],
    limit: int = Query(default=5, ge=1, le=10),
) -> SimilarProductResponse:
    if not bool(_entitlements(user)["recommendations.advanced"]):
        raise HTTPException(status_code=403, detail="Advanced recommendations required.")
    try:
        target = get_owned_scan_result(scan_id, user)
    except ScanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Scan not found.") from exc
    target_values = _observed_nutrients(target)
    candidates: list[SimilarProductCandidate] = []
    for candidate in _owned_scans(user)[:25]:
        if candidate.scan_id == scan_id or candidate.nutrition.basis != target.nutrition.basis:
            continue
        candidate_values = _observed_nutrients(candidate)
        shared = sorted(target_values.keys() & candidate_values.keys())
        if len(shared) < 2:
            continue
        component_scores = [
            1
            - abs(target_values[name] - candidate_values[name])
            / max(target_values[name], candidate_values[name], 1)
            for name in shared
        ]
        score = round(sum(component_scores) / len(component_scores), 4)
        product_name = (
            candidate.product_name_candidates[0].value
            if candidate.product_name_candidates
            else f"Scan {candidate.scan_id[:8]}"
        )
        candidates.append(
            SimilarProductCandidate(
                scan_id=candidate.scan_id,
                product_name=product_name,
                similarity=score,
                compared_nutrients=shared,
                evidence=[
                    f"{name}: {candidate_values[name]:g} vs {target_values[name]:g}"
                    for name in shared
                ],
            )
        )
    candidates.sort(key=lambda item: (-item.similarity, item.product_name.casefold()))
    selected = candidates[:limit]
    return SimilarProductResponse(
        scan_id=scan_id,
        state="AVAILABLE" if selected else "INSUFFICIENT_COMPARABLE_EVIDENCE",
        candidates=selected,
    )


def _require_owned_product_scan(scan_id: str, user: User) -> R3ScanResult:
    try:
        return get_owned_scan_result(scan_id, user)
    except ScanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Scan not found.") from exc


_ASSISTANT_NUTRIENTS: dict[str, tuple[tuple[str, ...], frozenset[str]]] = {
    "energy": (("energy", "calorie", "calories"), frozenset({"kcal", "kj"})),
    "protein": (("protein",), frozenset({"g", "mg"})),
    "carbohydrate": (("carbohydrate", "carbohydrates", "carbs"), frozenset({"g", "mg"})),
    "total sugar": (("total sugar", "total sugars", "sugar", "sugars"), frozenset({"g", "mg"})),
    "added sugar": (("added sugar", "added sugars"), frozenset({"g", "mg"})),
    "total fat": (("total fat", "fat"), frozenset({"g", "mg"})),
    "saturated fat": (("saturated fat",), frozenset({"g", "mg"})),
    "trans fat": (("trans fat",), frozenset({"g", "mg"})),
    "cholesterol": (("cholesterol",), frozenset({"g", "mg"})),
    "sodium": (("sodium",), frozenset({"g", "mg"})),
    "calcium": (("calcium",), frozenset({"g", "mg"})),
    "fiber": (("dietary fiber", "dietary fibre", "fiber", "fibre"), frozenset({"g", "mg"})),
    "iron": (("iron",), frozenset({"mg", "mcg", "µg", "ug"})),
    "potassium": (("potassium",), frozenset({"g", "mg"})),
    "vitamin a": (("vitamin a",), frozenset({"mg", "mcg", "µg", "ug"})),
    "vitamin c": (("vitamin c",), frozenset({"mg", "mcg", "µg", "ug"})),
    "vitamin d": (("vitamin d",), frozenset({"mg", "mcg", "µg", "ug"})),
    "zinc": (("zinc",), frozenset({"mg", "mcg", "µg", "ug"})),
}
_ASSISTANT_BASES = {
    "PER_100_G": "per 100 g",
    "PER_100_ML": "per 100 ml",
    "PER_SERVING": "per serving",
}
_ASSISTANT_AMOUNT = re.compile(
    r"(?P<amount>(?:[<>]=?\s*)?\d+(?:\.\d+)?)\s*(?P<unit>kcal|kj|mg|mcg|µg|ug|g|%)?",
    re.IGNORECASE,
)


def _scan_nutrition_facts(scan: R3ScanResult, wanted: set[str]) -> list[str]:
    """Quote bounded structured values; never infer units or calculate portions."""
    facts: list[str] = []
    nutrition = scan.nutrition
    for row in nutrition.table_rows[:100]:
        label = (row.canonical_label or row.label).casefold().strip()
        canonical = next(
            (name for name, (aliases, _) in _ASSISTANT_NUTRIENTS.items() if label in aliases),
            None,
        )
        if canonical is None or (wanted and canonical not in wanted):
            continue
        units_allowed = _ASSISTANT_NUTRIENTS[canonical][1]
        columns = [column.casefold().strip() for column in nutrition.table_columns]
        # R3 can retain an RDA header while omitting its percentage cells.
        if len(columns) != len(row.values):
            amount_columns = [column for column in columns if "%" not in column]
            columns = amount_columns if len(amount_columns) == len(row.values) else []
        for index, value in enumerate(row.values[:5]):
            match = _ASSISTANT_AMOUNT.fullmatch(value.strip())
            if match is None:
                continue
            inline_unit = (match.group("unit") or "").casefold()
            stored_unit = row.units[index].casefold().strip() if index < len(row.units) else ""
            if inline_unit and stored_unit and inline_unit != stored_unit:
                continue
            unit = inline_unit or stored_unit
            if unit not in units_allowed:
                continue
            column = columns[index] if index < len(columns) else ""
            if "%" in column:
                continue
            if column not in _ASSISTANT_BASES.values():
                column = (
                    _ASSISTANT_BASES.get(nutrition.basis, "basis unknown")
                    if len(row.values) == 1 and not nutrition.table_columns
                    else "basis/column association unknown"
                )
            facts.append(f"{canonical.capitalize()}: {match.group('amount')} {unit} ({column})")
    return facts


_STANDOUT_QUERY_PATTERN = re.compile(
    r"\b(what stands out|stand(?:s)? out|notable|key takeaways?|highlights?|"
    r"what to watch|anything notable|noteworthy)\b",
    re.I,
)


def _scan_standout_observations(scan: R3ScanResult) -> tuple[str, list[str]]:
    """Build deterministic, provenance-backed standout observations from structured scan fields."""
    evidence: list[str] = []
    observations: list[str] = ["What stands out from the current scan evidence:"]
    nutrition = scan.nutrition

    product_candidates = getattr(scan, "product_name_candidates", []) or []
    if product_candidates:
        prod_val = product_candidates[0].value.strip()[:160]
        if prod_val:
            item = (
                f"Product identity: {prod_val} [provenance: scan.product_name_candidates[0].value]"
            )
            evidence.append(item)
            observations.append(item)
    brand_candidates = getattr(scan, "brand_candidates", []) or []
    if brand_candidates:
        brand_val = brand_candidates[0].value.strip()[:160]
        if brand_val:
            item = f"Brand identity: {brand_val} [provenance: scan.brand_candidates[0].value]"
            evidence.append(item)
            observations.append(item)

    basis_label = _ASSISTANT_BASES.get(nutrition.basis)
    serving_val = nutrition.serving_size_value
    serving_unit = nutrition.serving_size_unit
    has_serving = bool(
        serving_val and serving_unit in {"g", "ml"} and re.fullmatch(r"\d+(?:\.\d+)?", serving_val)
    )
    if basis_label and has_serving:
        ctx = (
            f"Explicit serving and basis context: reported {basis_label} with "
            f"{serving_val} {serving_unit} serving size "
            "[provenance: scan.nutrition.basis] "
            "[provenance: scan.nutrition.serving_size_value]"
        )
        evidence.append(ctx)
        observations.append(ctx)
    elif basis_label:
        ctx = f"Explicit basis context: reported {basis_label} [provenance: scan.nutrition.basis]"
        evidence.append(ctx)
        observations.append(ctx)
    elif has_serving:
        ctx = (
            f"Explicit serving context: {serving_val} {serving_unit} "
            "[provenance: scan.nutrition.serving_size_value, scan.nutrition.serving_size_unit]"
        )
        evidence.append(ctx)
        observations.append(ctx)

    is_liquid = nutrition.basis == "PER_100_ML" or serving_unit == "ml"
    facts_by_nutrient: dict[str, list[tuple[float, str, str]]] = {}
    columns = [col.casefold().strip() for col in nutrition.table_columns]

    for row in nutrition.table_rows[:100]:
        label = (getattr(row, "canonical_label", None) or row.label).casefold().strip()
        canonical = next(
            (name for name, (aliases, _) in _ASSISTANT_NUTRIENTS.items() if label in aliases),
            None,
        )
        if canonical is None:
            continue
        units_allowed = _ASSISTANT_NUTRIENTS[canonical][1]
        parsed_values = getattr(row, "parsed_values", []) or []
        if parsed_values:
            for pv in parsed_values[:5]:
                unit = (pv.unit or "").casefold().strip()
                if unit not in units_allowed:
                    continue
                if pv.basis in {"PERCENT_RDA", "PERCENT_DV"} or getattr(
                    pv, "is_reference_intake", False
                ):
                    continue
                col = _ASSISTANT_BASES.get(pv.basis, "basis/column association unknown")
                amt_str = pv.value.lstrip("<>=").strip()
                try:
                    amt = float(amt_str)
                except ValueError:
                    continue
                facts_by_nutrient.setdefault(canonical, []).append((amt, unit, col))
            continue

        row_cols = list(columns)
        if len(row_cols) != len(row.values):
            amount_cols = [c for c in row_cols if "%" not in c]
            row_cols = amount_cols if len(amount_cols) == len(row.values) else []
        for idx, raw_val in enumerate(row.values[:5]):
            match = _ASSISTANT_AMOUNT.fullmatch(raw_val.strip())
            if match is None:
                continue
            inline_unit = (match.group("unit") or "").casefold()
            stored_unit = row.units[idx].casefold().strip() if idx < len(row.units) else ""
            unit = inline_unit or stored_unit
            if unit not in units_allowed:
                continue
            col = row_cols[idx] if idx < len(row_cols) else ""
            if "%" in col:
                continue
            if col not in _ASSISTANT_BASES.values():
                col = (
                    _ASSISTANT_BASES.get(nutrition.basis, "basis unknown")
                    if len(row.values) == 1 and not nutrition.table_columns
                    else "basis/column association unknown"
                )
            amt_str = match.group("amount").lstrip("<>=").strip()
            try:
                amt = float(amt_str)
            except ValueError:
                continue
            facts_by_nutrient.setdefault(canonical, []).append((amt, unit, col))

    def _format_entries(entries: list[tuple[float, str, str]]) -> str:
        parts = []
        for amt, unit, col in entries:
            amt_disp = f"{amt:g}"
            parts.append(f"{amt_disp} {unit} ({col})")
        return ", ".join(parts)

    def _per_100_amount(entries: list[tuple[float, str, str]]) -> float | None:
        for amt, _u, col in entries:
            if col in {"per 100 g", "per 100 ml"}:
                return amt
        return None

    def _per_serving_amount(entries: list[tuple[float, str, str]]) -> float | None:
        for amt, _u, col in entries:
            if col == "per serving":
                return amt
        return None

    if "energy" in facts_by_nutrient:
        entries = facts_by_nutrient["energy"]
        obs = (
            f"Declared energy: {_format_entries(entries)} "
            "[provenance: scan.nutrition.table_rows[energy]]"
        )
        evidence.append(obs)
        observations.append(obs)

    if "protein" in facts_by_nutrient:
        entries = facts_by_nutrient["protein"]
        p100 = _per_100_amount(entries)
        pserv = _per_serving_amount(entries)
        notable = (pserv is not None and pserv >= 5.0) or (p100 is not None and p100 >= 3.0)
        prefix = "Notable protein signal" if notable else "Declared protein"
        obs = (
            f"{prefix}: {_format_entries(entries)} [provenance: scan.nutrition.table_rows[protein]]"
        )
        evidence.append(obs)
        observations.append(obs)

    if "added sugar" in facts_by_nutrient:
        entries = facts_by_nutrient["added sugar"]
        p100 = _per_100_amount(entries)
        high_thresh = 5.0 if is_liquid else 10.0
        if all(amt == 0.0 for amt, _u, _c in entries):
            prefix = "Low added sugar signal (0 g declared)"
        elif p100 is not None and p100 >= high_thresh:
            prefix = "High relative added sugar signal"
        else:
            prefix = "Declared added sugar"
        obs = (
            f"{prefix}: {_format_entries(entries)} "
            "[provenance: scan.nutrition.table_rows[added sugar]]"
        )
        evidence.append(obs)
        observations.append(obs)

    if "total sugar" in facts_by_nutrient:
        entries = facts_by_nutrient["total sugar"]
        p100 = _per_100_amount(entries)
        high_thresh = 11.25 if is_liquid else 22.5
        low_thresh = 2.5 if is_liquid else 5.0
        if p100 is not None and p100 >= high_thresh:
            prefix = "High relative total sugar signal"
        elif p100 is not None and p100 <= low_thresh:
            prefix = "Low relative total sugar signal"
        else:
            prefix = "Declared total sugar"
        obs = (
            f"{prefix}: {_format_entries(entries)} "
            "[provenance: scan.nutrition.table_rows[total sugar]]"
        )
        evidence.append(obs)
        observations.append(obs)

    if "total fat" in facts_by_nutrient:
        entries = facts_by_nutrient["total fat"]
        p100 = _per_100_amount(entries)
        high_thresh = 8.75 if is_liquid else 17.5
        low_thresh = 1.5 if is_liquid else 3.0
        if p100 is not None and p100 >= high_thresh:
            prefix = "High relative total fat signal"
        elif p100 is not None and p100 <= low_thresh:
            prefix = "Low relative total fat signal"
        else:
            prefix = "Declared total fat"
        obs = (
            f"{prefix}: {_format_entries(entries)} "
            "[provenance: scan.nutrition.table_rows[total fat]]"
        )
        evidence.append(obs)
        observations.append(obs)

    if "saturated fat" in facts_by_nutrient:
        entries = facts_by_nutrient["saturated fat"]
        p100 = _per_100_amount(entries)
        high_thresh = 2.5 if is_liquid else 5.0
        low_thresh = 0.75 if is_liquid else 1.5
        if p100 is not None and p100 >= high_thresh:
            prefix = "High relative saturated fat signal"
        elif p100 is not None and p100 <= low_thresh:
            prefix = "Low relative saturated fat signal"
        else:
            prefix = "Declared saturated fat"
        obs = (
            f"{prefix}: {_format_entries(entries)} "
            "[provenance: scan.nutrition.table_rows[saturated fat]]"
        )
        evidence.append(obs)
        observations.append(obs)

    if "sodium" in facts_by_nutrient:
        entries = facts_by_nutrient["sodium"]
        p100 = _per_100_amount(entries)
        if p100 is not None and p100 >= 600.0:
            prefix = "High relative sodium signal"
        elif p100 is not None and p100 <= 120.0:
            prefix = "Low relative sodium signal"
        else:
            prefix = "Declared sodium"
        obs = (
            f"{prefix}: {_format_entries(entries)} [provenance: scan.nutrition.table_rows[sodium]]"
        )
        evidence.append(obs)
        observations.append(obs)

    for extra_key in ("carbohydrate", "fiber", "trans fat", "cholesterol", "calcium"):
        if extra_key in facts_by_nutrient:
            entries = facts_by_nutrient[extra_key]
            obs = (
                f"Declared {extra_key}: {_format_entries(entries)} "
                f"[provenance: scan.nutrition.table_rows[{extra_key}]]"
            )
            evidence.append(obs)
            observations.append(obs)

    allergen_stmt = scan.ingredients.allergen_text.strip()
    if allergen_stmt:
        obs = (
            f"Declared allergen statement: {allergen_stmt[:400]} "
            "[provenance: scan.ingredients.allergen_text]"
        )
        evidence.append(obs)
        observations.append(obs)

    ing_stmt = scan.ingredients.raw_text.strip()
    if ing_stmt:
        obs = f"Declared ingredients: {ing_stmt[:400]} [provenance: scan.ingredients.raw_text]"
        evidence.append(obs)
        observations.append(obs)

    has_substantive_evidence = bool(facts_by_nutrient or allergen_stmt or ing_stmt)
    if not has_substantive_evidence:
        return (
            "Current scan evidence is insufficient to determine what stands out: "
            "no structured nutrition values, ingredient list, or allergen declaration "
            "were recovered from this scan. Please inspect the physical package label.",
            [],
        )

    observations.append(
        "All observations are derived strictly from extracted current-scan fields "
        "without inferred conversions."
    )
    return "\n".join(observations), evidence


def _scan_assistant_answer(scan: R3ScanResult, question: str) -> tuple[str, list[str]]:
    """Keep package observations separate from health claims and external retrieval."""
    lowered = question.casefold()
    if _STANDOUT_QUERY_PATTERN.search(lowered):
        return _scan_standout_observations(scan)
    summary = bool(
        re.search(r"\b(explain|summari[sz]e|summary)\b", lowered)
        or re.search(r"\bwhat does (this |the )?scan (mean|show)\b", lowered)
    )
    allergens = bool(
        re.search(r"\b(allergens?|allergy|allergies|allergic|safe|safety)\b", lowered)
        or re.search(
            r"\b(contain|contains|free from)\b.*"
            r"\b(milk|dairy|nuts?|soy|wheat|eggs?|gluten|sesame|fish|shellfish)\b",
            lowered,
        )
    )
    ingredients = bool(re.search(r"\bingredients?\b", lowered))
    nutrition = bool(re.search(r"\b(nutrition|nutrients?|nutritional)\b", lowered))
    wanted = {
        name
        for name, (aliases, _) in _ASSISTANT_NUTRIENTS.items()
        if any(re.search(rf"\b{re.escape(alias)}\b", lowered) for alias in aliases)
    }
    if "added sugar" in wanted and not re.search(r"\btotal sugars?\b", lowered):
        wanted.discard("total sugar")
    if wanted.intersection({"saturated fat", "trans fat"}) and "total fat" not in lowered:
        wanted.discard("total fat")
    evidence: list[str] = []
    notes: list[str] = []
    if summary:
        if scan.product_name_candidates:
            evidence.append(
                f"Package product candidate / OCR: {scan.product_name_candidates[0].value[:200]}"
            )
        if scan.brand_candidates:
            evidence.append(
                f"Package brand candidate / OCR: {scan.brand_candidates[0].value[:200]}"
            )
    if summary or ingredients:
        if scan.ingredients.raw_text.strip():
            evidence.append(
                f"Package ingredient extraction / OCR: {scan.ingredients.raw_text[:1000]}"
            )
        else:
            notes.append("Ingredient evidence is unavailable in this scan.")
    if summary or allergens:
        statement = scan.ingredients.allergen_text.strip()
        if statement:
            # Quote the statement itself: do not turn 'may contain' into 'contains',
            # or a negative/free-from declaration into positive allergen evidence.
            evidence.append(f"Package allergen statement / OCR: {statement[:1000]}")
        else:
            notes.append("No explicit package allergen statement was recovered in this scan.")
        notes.append(
            "Missing or incomplete OCR is not evidence of absence and does not establish "
            "allergy safety. Check the package declaration; this answer cannot certify it safe."
        )
    if summary or nutrition or wanted:
        facts = _scan_nutrition_facts(scan, set() if summary or nutrition else wanted)
        evidence.extend(f"Package nutrition extraction / OCR: {fact}" for fact in facts[:40])
        serving_value = scan.nutrition.serving_size_value
        serving_unit = scan.nutrition.serving_size_unit
        if (
            serving_value
            and serving_unit in {"g", "ml"}
            and re.fullmatch(r"\d+(?:\.\d+)?", serving_value)
        ):
            evidence.append(f"Package serving size / OCR: {serving_value} {serving_unit}")
        else:
            notes.append("Serving size is unknown from the structured scan.")
        if not facts:
            notes.append("The requested nutrition amount is unknown from the structured scan.")
        elif wanted and not summary and not nutrition:
            for name in sorted(wanted):
                if not any(fact.casefold().startswith(f"{name}:") for fact in facts):
                    notes.append(f"{name.capitalize()} amount is unknown from the structured scan.")
        if "per serving" in lowered and not any("(per serving)" in fact for fact in facts):
            notes.append("A label-reported per-serving amount is unavailable for this request.")
        notes.append(
            "These are extracted label values, not verified measurements. "
            "No serving or unit conversion was inferred."
        )
    if not (summary or allergens or ingredients or nutrition or wanted):
        return (
            "The available scan evidence is insufficient for that conclusion, so the answer "
            "is unknown. Ask me to explain the scan, its ingredient/allergen statement, or "
            "a label-reported nutrient amount.",
            [],
        )
    answer = "\n".join([*evidence, *notes])
    return answer, evidence


AssistantIntent = Literal[
    "OUT_OF_SCOPE",
    "CURRENT_SCAN_ALLERGEN",
    "CURRENT_SCAN_INGREDIENT",
    "CURRENT_SCAN_NUTRITION",
    "PERSONAL_FIT_CONTEXT",
    "COMPARE_FOODS",
    "DIARY_CONTEXT",
    "PANTRY_CONTEXT",
    "USER_GOAL_CONTEXT",
    "GENERAL_NUTRITION_EDUCATION",
]


def _detect_assistant_intent(message: str, scan: R3ScanResult | None = None) -> AssistantIntent:
    lowered = message.casefold().strip()

    # 1. OUT_OF_SCOPE (medical, clinical diagnosis, prescriptions, curing disease)
    if re.search(
        r"\b(cure|cures|curing|diagnos(e|is|es)|prescrib(e|tion)|treat(ing|ment)?\s+disease|cure\s+disease|medication)\b",
        lowered,
    ):
        return "OUT_OF_SCOPE"

    # 2. PERSONAL_FIT_CONTEXT (fit score, personal fit, alternatives, suitability, good/bad)
    fit_pattern = (
        r"\b(fit score|personal fit|how does this fit|good or bad|is this good|is this bad|"
        r"why is this food|why this score|better alternatives?|healthy for me|suitable for me|"
        r"suitable for my|what should i choose instead|choose instead)\b"
    )
    if re.search(fit_pattern, lowered):
        return "PERSONAL_FIT_CONTEXT"

    # 3. CURRENT_SCAN_ALLERGEN
    allergen_terms = r"\b(allerg(y|ies|en|ens|ic)|safe|safety)\b"
    specific_allergens = (
        r"\b(contain|contains|free from)\b.*\b"
        r"(milk|dairy|nuts?|peanuts?|soy|wheat|eggs?|gluten|sesame|fish|shellfish)\b"
    )
    if (re.search(allergen_terms, lowered) or re.search(specific_allergens, lowered)) and (
        scan is not None or re.search(r"\b(this|the|scan|product|package|food)\b", lowered)
    ):
        return "CURRENT_SCAN_ALLERGEN"

    # 4. CURRENT_SCAN_INGREDIENT
    if re.search(
        r"\b(ingredients?|additives?|preservatives?|what is in (this|the))\b", lowered
    ) and (scan is not None or re.search(r"\b(this|the|scan|product|package)\b", lowered)):
        return "CURRENT_SCAN_INGREDIENT"

    # 5. CURRENT_SCAN_NUTRITION
    has_nutrient_ask = any(
        re.search(rf"\b{re.escape(alias)}\b", lowered)
        for aliases, _ in _ASSISTANT_NUTRIENTS.values()
        for alias in aliases
    )
    is_scan_specific = bool(
        scan is not None
        or re.search(r"\b(this|the|package|product|scan|serving)\b", lowered)
        or re.search(r"\bhow much\b", lowered)
    )
    if (
        _STANDOUT_QUERY_PATTERN.search(lowered)
        or re.search(r"\b(explain|summari[sz]e|summary)\b", lowered)
        or re.search(r"\bwhat does (this |the )?scan (mean|show)\b", lowered)
        or (
            scan is not None
            and (has_nutrient_ask or re.search(r"\b(nutrition|nutrients?|nutritional)\b", lowered))
        )
        or (
            has_nutrient_ask
            and is_scan_specific
            and not re.search(r"\b(what (is|does|are)|why is|how should|role of)\b", lowered)
        )
    ):
        return "CURRENT_SCAN_NUTRITION"

    # 5. COMPARE_FOODS
    compare_pattern = (
        r"\b(compare|difference between|versus|vs\.?|"
        r"which (is|has) (more|less|better|healthier))\b"
    )
    if re.search(compare_pattern, lowered):
        return "COMPARE_FOODS"

    # 6. DIARY_CONTEXT
    diary_pattern = (
        r"\b(diary|what did i eat|my intake|logged today|"
        r"track(ed)? today|today'?s food|eaten today)\b"
    )
    if re.search(diary_pattern, lowered):
        return "DIARY_CONTEXT"

    # 7. PANTRY_CONTEXT
    if re.search(
        r"\b(pantry|what can i cook|what do i have|cook with|recipe with|my ingredients)\b",
        lowered,
    ):
        return "PANTRY_CONTEXT"

    # 8. USER_GOAL_CONTEXT
    if re.search(
        r"\b(my goal|target|daily goal|am i on track|progress towards|nutrition goal)\b",
        lowered,
    ):
        return "USER_GOAL_CONTEXT"

    # 9. GENERAL_NUTRITION_EDUCATION
    return "GENERAL_NUTRITION_EDUCATION"


@router.post("/assistant/messages", response_model=AssistantResponse)
def assistant_message(
    payload: AssistantRequest, user: Annotated[User, Depends(current_user)]
) -> AssistantResponse:
    scan = (
        _require_owned_product_scan(payload.scan_id, user) if payload.scan_id is not None else None
    )
    allowance = int(_entitlements(user)["assistant.daily_limit"])
    today = datetime.now(UTC).date()
    used = product_store.reserve_assistant(user.id, today, allowance)
    if used is None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily assistant allowance reached.",
        )
    try:
        intent = _detect_assistant_intent(payload.message, scan)

        if intent == "OUT_OF_SCOPE":
            product_store.release_assistant(user.id, today)
            return AssistantResponse(
                answer=(
                    "NutriLens provides nutritional education and evidence from food labels, "
                    "not clinical diagnoses, treatments, or medical prescriptions. "
                    "Consult a qualified healthcare professional for medical advice."
                ),
                evidence=[],
                citations=[],
                remaining_today=max(0, allowance - (used - 1)),
                generation_mode="CLINICAL_BOUNDARY_SAFEGUARD",
            )

        if intent in {"CURRENT_SCAN_NUTRITION", "CURRENT_SCAN_INGREDIENT", "CURRENT_SCAN_ALLERGEN"}:
            if scan is not None:
                scan_answer, scan_evidence = _scan_assistant_answer(scan, payload.message)
                return AssistantResponse(
                    answer=scan_answer,
                    evidence=scan_evidence,
                    citations=[],
                    remaining_today=max(0, allowance - used),
                    generation_mode="DETERMINISTIC_SCAN_EVIDENCE",
                    method="OWNER_SCOPED_STRUCTURED_SCAN_ASSISTANT_V1",
                )
            else:
                product_store.release_assistant(user.id, today)
                return AssistantResponse(
                    answer=(
                        "No active food scan is selected. Scan a package first "
                        "to inspect its ingredients, allergens, or nutrition facts."
                    ),
                    evidence=[],
                    citations=[],
                    remaining_today=max(0, allowance - (used - 1)),
                    generation_mode="NO_ACTIVE_SCAN",
                )

        if intent == "PERSONAL_FIT_CONTEXT":
            if scan is not None:
                recs_resp = scan_recommendations(scan.scan_id, user)
                fs = recs_resp.fit_score
                parts = []
                evidence = []
                if fs and fs.score is not None:
                    parts.append(
                        f"Your Personal Fit Score for this item is {fs.score}/100 ({fs.label})."
                    )
                    evidence.append(f"Personal Fit Score: {fs.score}/100")
                elif fs:
                    parts.append(f"Personal Fit status: {fs.label}.")
                    evidence.append(f"Personal Fit: {fs.label}")
                if fs and fs.reasons:
                    parts.append("Key reasons: " + " ".join(fs.reasons))
                    evidence.extend(fs.reasons[:3])
                if recs_resp.better_alternatives:
                    alt_names = [a.name for a in recs_resp.better_alternatives]
                    parts.append(f"Verified catalogue alternatives: {', '.join(alt_names)}.")
                    evidence.extend(
                        [
                            f"Alternative: {a.name} ({a.why_better})"
                            for a in recs_resp.better_alternatives
                        ]
                    )
                elif "alternative" in payload.message.casefold():
                    parts.append(
                        "No verified catalogue alternatives are currently recorded for this item."
                    )
                parts.append(
                    "NutriLens provides wellness educational context, "
                    "not medical diagnosis or prescription."
                )
                return AssistantResponse(
                    answer=" ".join(parts),
                    evidence=evidence,
                    citations=[],
                    remaining_today=max(0, allowance - used),
                    generation_mode="PERSONAL_FIT_GROUNDED",
                    method="PROFILE_AND_SCAN_PERSONAL_FIT_V1",
                )
            else:
                product_store.release_assistant(user.id, today)
                return AssistantResponse(
                    answer=(
                        "No active food scan is selected. Scan a packaged product first "
                        "to check your Personal Fit score."
                    ),
                    evidence=[],
                    citations=[],
                    remaining_today=max(0, allowance - (used - 1)),
                    generation_mode="NO_ACTIVE_SCAN",
                )

        if intent == "COMPARE_FOODS":
            product_store.release_assistant(user.id, today)
            return AssistantResponse(
                answer=(
                    "To compare foods, open the Compare screen where you can select "
                    "two food scans or saved items to view their nutrition and "
                    "ingredients side-by-side."
                ),
                evidence=[],
                citations=[],
                remaining_today=max(0, allowance - (used - 1)),
                generation_mode="COMPARE_ROUTING",
            )

        if intent == "DIARY_CONTEXT":
            cutoff = datetime.now(UTC) - timedelta(days=7)
            today_entries = [
                e for e in product_store.list_diary(user.id, cutoff) if e.eaten_at.date() == today
            ]
            if today_entries:
                names = [e.name for e in today_entries]
                known_cals = [
                    e.nutrients.calories for e in today_entries if e.nutrients.calories is not None
                ]
                known_proteins = [
                    e.nutrients.protein_g
                    for e in today_entries
                    if e.nutrients.protein_g is not None
                ]
                cals_str = f"{sum(known_cals):.0f} kcal" if known_cals else "unknown"
                protein_str = f"{sum(known_proteins):.1f} g" if known_proteins else "unknown"
                answer = (
                    f"Today you logged {len(today_entries)} item(s) in your diary: "
                    f"{', '.join(names)}. "
                    f"Total logged energy: {cals_str}, protein: {protein_str}."
                )
                evidence = [
                    (
                        f"{e.name}: {e.nutrients.calories:.0f} kcal"
                        if e.nutrients.calories is not None
                        else f"{e.name}: calories unknown"
                    )
                    for e in today_entries
                ]
            else:
                answer = "You haven't logged any foods in your diary for today yet."
                evidence = []
            return AssistantResponse(
                answer=answer,
                evidence=evidence,
                citations=[],
                remaining_today=max(0, allowance - used),
                generation_mode="DIARY_CONTEXT_ANSWER",
            )

        if intent == "PANTRY_CONTEXT":
            pantry = product_store.list_pantry(user.id)
            if pantry:
                names = [p.name for p in pantry]
                recs = recipe_recommendations(user)
                top_titles = [r.title for r in recs[:3]]
                answer = (
                    f"Your pantry currently has {len(pantry)} item(s): {', '.join(names[:5])}. "
                    f"Based on your stock, matching recipes include: {', '.join(top_titles)}."
                )
                evidence = [f"Pantry: {item.name}" for item in pantry[:10]]
            else:
                answer = (
                    "Your pantry is currently empty. "
                    "Add items to your pantry to get recipe suggestions based on what you have."
                )
                evidence = []
            return AssistantResponse(
                answer=answer,
                evidence=evidence,
                citations=[],
                remaining_today=max(0, allowance - used),
                generation_mode="PANTRY_CONTEXT_ANSWER",
            )

        if intent == "USER_GOAL_CONTEXT":
            user_profile = _profile(user.id)
            has_profile_context = user_profile and (
                user_profile.goal
                or user_profile.health_conditions
                or user_profile.dietary_style != "No specific diet"
            )
            if user_profile and has_profile_context:
                goal_desc = (
                    user_profile.custom_goal or user_profile.goal.replace("-", " ").capitalize()
                )
                conditions_str = (
                    f" Health conditions noted: {', '.join(user_profile.health_conditions)}."
                    if user_profile.health_conditions
                    else ""
                )
                style_str = (
                    f" Dietary style: {user_profile.dietary_style}."
                    if user_profile.dietary_style != "No specific diet"
                    else ""
                )
                answer = (
                    f"Your active wellness goal is '{user_profile.goal}' ({goal_desc})."
                    f"{style_str}{conditions_str} "
                    f"Guidance is calibrated to respect these preferences. "
                    f"Wellness decision support only; not medical advice or prescription."
                )
                evidence = [f"Goal: {user_profile.goal}"]
                if user_profile.dietary_style != "No specific diet":
                    evidence.append(f"Dietary style: {user_profile.dietary_style}")
                if user_profile.health_conditions:
                    evidence.append(f"Conditions: {', '.join(user_profile.health_conditions)}")
            else:
                answer = (
                    "You haven't set a nutrition goal yet. "
                    "You can choose a goal in your Profile or Settings."
                )
                evidence = []
            return AssistantResponse(
                answer=answer,
                evidence=evidence,
                citations=[],
                remaining_today=max(0, allowance - used),
                generation_mode="GOAL_CONTEXT_ANSWER",
            )

        # GENERAL_NUTRITION_EDUCATION (and fallback):
        # 1. Primary authority governed nutrition education
        effect_records = retrieve_health_effects(payload.message)
        if effect_records:
            effect = effect_records[0]
            evidence = [effect.role_summary]
            citations = [
                AssistantCitation(
                    evidence_id=f"EVD-ROLE-{effect.nutrient_id.upper()}",
                    title=effect.title,
                    authority=effect.authority,
                    url=effect.url,
                )
            ]
            answer = f"{effect.role_summary} {effect.caution}"
            generated = generate_assistant_answer(
                question=payload.message,
                evidence=evidence,
                deterministic_answer=answer,
            )
            return AssistantResponse(
                answer=generated.text or answer,
                evidence=evidence,
                citations=citations,
                remaining_today=max(0, allowance - used),
                generation_mode=generated.mode,
            )

        # 2. Food taxonomy lookup
        retrieved = retrieve_knowledge(payload.message)
        if retrieved:
            evidence = [
                item.record.canonical_name
                for item in retrieved
                if item.record.canonical_name is not None
            ]
            references = {
                reference.evidence_id: reference
                for item in retrieved
                for reference in item.record.references
            }
            citations = [
                AssistantCitation(
                    evidence_id=ref.evidence_id,
                    title=ref.title,
                    authority=ref.authority,
                    url=ref.url,
                )
                for ref in references.values()
            ]
            answer = (
                "The governed food taxonomy matched these label terms: "
                f"{', '.join(evidence)}. "
                "This establishes taxonomy identity, not a health verdict."
            )
            generated = generate_assistant_answer(
                question=payload.message,
                evidence=evidence,
                deterministic_answer=answer,
            )
            return AssistantResponse(
                answer=generated.text or answer,
                evidence=evidence,
                citations=citations,
                remaining_today=max(0, allowance - used),
                generation_mode=generated.mode,
            )

        # 3. Fallback generic capability explanation (does NOT charge quota)
        product_store.release_assistant(user.id, today)
        return AssistantResponse(
            answer=(
                "I can explain food evidence and relate it to preferences you have chosen to share."
            ),
            evidence=[],
            citations=[],
            remaining_today=max(0, allowance - (used - 1)),
            generation_mode="CAPABILITY_EXPLANATION",
        )
    except Exception:
        # Technical failure: safely refund reserved quota
        product_store.release_assistant(user.id, today)
        raise


@router.get("/research/aggregate", response_model=ResearchAggregate)
def research_aggregate(user: Annotated[User, Depends(current_user)]) -> ResearchAggregate:
    if SpecialRole.RESEARCHER not in user.roles and SpecialRole.ADMIN not in user.roles:
        raise HTTPException(status_code=403, detail="Researcher role required.")
    minimum_cohort = 20
    window = int(time() // 3600)
    user_count, entry_count, totals = _research_window_summary(
        window, product_store.research_summary
    )
    if user_count < minimum_cohort:
        return ResearchAggregate(
            state="INSUFFICIENT_COHORT",
            minimum_cohort=minimum_cohort,
            deidentified_user_count=None,
            diary_entry_count=None,
            nutrient_totals=None,
        )
    return ResearchAggregate(
        state="AVAILABLE",
        minimum_cohort=minimum_cohort,
        deidentified_user_count=(user_count // 20) * 20,
        diary_entry_count=None,
        nutrient_totals=None,
    )


@lru_cache(maxsize=32)
def _research_window_summary(
    window: int, summary_function: Any
) -> tuple[int, int, NutrientSnapshot]:
    """Freeze one rounded research source snapshot per hour and store implementation."""
    del window
    return summary_function()  # type: ignore[no-any-return]


def _analytics_insights(averages: NutrientSnapshot, has_entries: bool) -> list[str]:
    if not has_entries:
        return ["Add diary entries to reveal evidence-based nutrition patterns."]
    populated = sum(getattr(averages, name) is not None for name in NutrientSnapshot.model_fields)
    return [
        f"Daily averages include {populated} nutrients with values for every logged entry; "
        "any missing nutrient values leave that nutrient's total and average unknown."
    ]


def _analytics_period_snapshot(
    first_date: date,
    last_date: date,
    entries: list[DiaryEntry],
) -> AnalyticsPeriodSnapshot:
    totals = _sum_nutrients(entry.nutrients for entry in entries)
    logged_days = len({entry.eaten_at.astimezone(UTC).date() for entry in entries})
    divisor = max(1, logged_days)
    averages = _scale_nutrients(totals, 1 / divisor)
    return AnalyticsPeriodSnapshot(
        first_date=first_date,
        last_date=last_date,
        logged_days=logged_days,
        diary_entries=len(entries),
        daily_averages=averages,
    )


_COMPARISON_METRICS = {
    "calories": ("Energy", "kcal/day"),
    "protein_g": ("Protein", "g/day"),
    "fiber_g": ("Fiber", "g/day"),
    "sugar_g": ("Sugar", "g/day"),
    "sodium_mg": ("Sodium", "mg/day"),
}


def _analytics_metric_changes(
    current: NutrientSnapshot,
    previous: NutrientSnapshot,
) -> list[AnalyticsMetricChange]:
    changes = []
    for nutrient, (label, unit) in _COMPARISON_METRICS.items():
        current_value = getattr(current, nutrient)
        previous_value = getattr(previous, nutrient)
        if current_value is None or previous_value is None:
            changes.append(
                AnalyticsMetricChange(
                    nutrient=nutrient,
                    label=label,
                    unit=unit,
                    direction="NOT_COMPARABLE",
                    absolute_change=None,
                    percent_change=None,
                )
            )
            continue
        difference = round(current_value - previous_value, 2)
        direction: Literal["HIGHER", "LOWER", "UNCHANGED", "NOT_COMPARABLE"]
        if difference > 0:
            direction = "HIGHER"
            absolute_change = difference
        elif difference < 0:
            direction = "LOWER"
            absolute_change = difference
        else:
            direction = "UNCHANGED"
            absolute_change = 0
        changes.append(
            AnalyticsMetricChange(
                nutrient=nutrient,
                label=label,
                unit=unit,
                direction=direction,
                absolute_change=absolute_change,
                percent_change=(
                    round((difference / previous_value) * 100, 1) if previous_value > 0 else None
                ),
            )
        )
    return changes


def _analytics_change_story(change: AnalyticsMetricChange) -> str:
    if change.direction == "NOT_COMPARABLE":
        return f"The {change.label.casefold()} total is incomplete in one or both windows."
    if change.direction == "UNCHANGED":
        return f"The logged daily {change.label.casefold()} average was unchanged."
    direction = "higher" if change.direction == "HIGHER" else "lower"
    magnitude = abs(change.absolute_change or 0)
    return (
        f"The logged daily {change.label.casefold()} average was {magnitude:g} "
        f"{change.unit} {direction} than in the adjacent previous window."
    )


_TARGET_METADATA = {
    "calories": ("Energy", "kcal"),
    "protein_g": ("Protein", "g"),
    "fiber_g": ("Fiber", "g"),
    "sodium_mg": ("Sodium", "mg"),
    "calcium_mg": ("Calcium", "mg"),
    "iron_mg": ("Iron", "mg"),
}


def _goal_progress(
    profile: HealthProfile, averages: NutrientSnapshot
) -> tuple[
    Literal["AVAILABLE", "NOT_CONFIGURED", "DISABLED_NO_CONSENT"],
    list[GoalProgress],
]:
    if not profile.consent_personalization:
        return "DISABLED_NO_CONSENT", []
    targets = profile.daily_targets.model_dump(exclude_none=True)
    if not targets:
        return "NOT_CONFIGURED", []
    progress = [
        GoalProgress(
            nutrient=nutrient,
            label=_TARGET_METADATA[nutrient][0],
            unit=_TARGET_METADATA[nutrient][1],
            daily_average=(
                round(getattr(averages, nutrient), 2)
                if getattr(averages, nutrient) is not None
                else None
            ),
            user_target=target,
            percent_of_target=(
                round((getattr(averages, nutrient) / target) * 100, 1)
                if getattr(averages, nutrient) is not None
                else None
            ),
        )
        for nutrient, target in targets.items()
    ]
    return "AVAILABLE", progress


def _spreadsheet_safe(value: str) -> str:
    return f"'{value}" if value.lstrip().startswith(("=", "+", "-", "@")) else value


_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_NUTRIENT_ALIASES = {
    "energy": ("energy", "calorie", "kcal"),
    "protein": ("protein",),
    "carbohydrate": ("carbohydrate", "carbs"),
    "fat": ("total fat", "fat"),
    "sugar": ("total sugar", "sugars", "sugar"),
    "fiber": ("dietary fiber", "dietary fibre", "fiber", "fibre"),
    "sodium": ("sodium",),
    "calcium": ("calcium",),
    "iron": ("iron",),
    "potassium": ("potassium",),
}


def _observed_nutrients(scan: R3ScanResult) -> dict[str, float]:
    if scan.nutrition.basis == "UNKNOWN":
        return {}
    values: dict[str, float] = {}
    for row in scan.nutrition.table_rows[:100]:
        label = row.label.casefold()
        canonical = next(
            (
                name
                for name, aliases in _NUTRIENT_ALIASES.items()
                if any(alias in label for alias in aliases)
            ),
            None,
        )
        if canonical is None:
            continue
        numeric = next(
            (
                float(match.group())
                for value in row.values[:5]
                if (match := _NUMBER.search(value)) is not None
            ),
            None,
        )
        if numeric is not None and numeric >= 0:
            values[canonical] = numeric
    return values


def _owned_scans(user: User) -> list[R3ScanResult]:
    if postgres_store is not None:
        return [
            R3ScanResult.model_validate(payload) for payload in postgres_store.list_scans(user.id)
        ]
    return scan_store.list(owner_id=user.id)


@lru_cache(maxsize=1)
def _recipe_bundle() -> dict[str, Any]:
    path = Path("data/runtime/recipe-templates-v0.2.0.json")
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _normalize_unit(unit: str | None) -> str:
    if not unit:
        return ""
    u = unit.strip().casefold()
    if u in {"g", "gram", "grams"}:
        return "g"
    if u in {"kg", "kilogram", "kilograms"}:
        return "kg"
    if u in {"ml", "milliliter", "milliliters", "millilitre", "millilitres"}:
        return "ml"
    if u in {"l", "liter", "liters", "litre", "litres"}:
        return "l"
    if u in {"unit", "units", "piece", "pieces", "count", "item", "items"}:
        return "unit"
    return u


def _convert_quantity(amount: float, from_unit: str, to_unit: str) -> float | None:
    norm_from = _normalize_unit(from_unit)
    norm_to = _normalize_unit(to_unit)
    if norm_from == norm_to:
        return amount
    if norm_from == "kg" and norm_to == "g":
        return amount * 1000.0
    if norm_from == "g" and norm_to == "kg":
        return amount / 1000.0
    if norm_from == "l" and norm_to == "ml":
        return amount * 1000.0
    if norm_from == "ml" and norm_to == "l":
        return amount / 1000.0
    return None


def _pantry_contains(pantry_names: list[str], ingredient: str) -> bool:
    normalized = ingredient.casefold()
    variants = {normalized, f"{normalized}s", f"{normalized}es"}
    return any(
        variant in pantry_name.split() or variant in pantry_name
        for pantry_name in pantry_names
        for variant in variants
    )


def _available_substitutions(
    bundle: dict[str, Any],
    missing_required: list[str],
    pantry_names: list[str],
) -> list[IngredientSubstitution]:
    missing = {item.casefold() for item in missing_required}
    substitutions: list[IngredientSubstitution] = []
    for entry in bundle.get("substitutions", []):
        ingredient = str(entry["ingredient"])
        if ingredient.casefold() not in missing:
            continue
        for alternative in entry.get("alternatives", []):
            alternative_name = str(alternative)
            if _pantry_contains(pantry_names, alternative_name):
                substitutions.append(
                    IngredientSubstitution(
                        missing_ingredient=ingredient,
                        available_alternative=alternative_name,
                        function=str(entry["function"]),
                        limitation=str(entry["limitation"]),
                    )
                )
    return substitutions[:10]


def _preparation_complexity(
    required: list[str],
    steps: list[Any],
) -> PreparationComplexity:
    score = len(required) + len(steps)
    band: Literal["BASIC", "MODERATE", "INVOLVED"] = (
        "BASIC" if score <= 4 else "MODERATE" if score <= 7 else "INVOLVED"
    )
    return PreparationComplexity(
        band=band,
        written_steps=len(steps),
        required_ingredients=len(required),
    )


def _create_expiry_notification(user_id: str, item: PantryItem) -> None:
    notification_id = f"pantry-expiry:{item.id}"
    if item.expires_on is None:
        product_store.delete_notification(user_id, notification_id)
        return
    days = (item.expires_on - datetime.now(UTC).date()).days
    if days > 3:
        product_store.delete_notification(user_id, notification_id)
        return
    timing = "today" if days == 0 else "already passed" if days < 0 else f"in {days} day(s)"
    product_store.upsert_notification(
        user_id,
        Notification(
            id=notification_id,
            kind="PANTRY_EXPIRY",
            title=f"Use {item.name} soon",
            body=f"The saved pantry expiry is {timing}. Verify the package date before use.",
            action_href="/dashboard",
        ),
    )


def _create_low_stock_notification(user_id: str, item: PantryItem) -> None:
    notification_id = f"pantry-low-stock:{item.id}"
    if item.low_stock_threshold is None or item.quantity > item.low_stock_threshold:
        product_store.delete_notification(user_id, notification_id)
        return
    product_store.upsert_notification(
        user_id,
        Notification(
            id=notification_id,
            kind="PANTRY_LOW_STOCK",
            title=f"Review {item.name} stock",
            body=(
                f"Your saved quantity is {item.quantity:g} {item.unit}, at or below your "
                f"{item.low_stock_threshold:g} {item.unit} threshold. Verify what you need "
                "before shopping."
            ),
            action_href="/dashboard",
        ),
    )


# =========================================================================
# Official Swiggy Instamart MCP Integration
# =========================================================================


class InstamartAddress(BaseModel):
    id: str
    label: str | None = None
    address_line: str
    latitude: float | None = None
    longitude: float | None = None


class InstamartProduct(BaseModel):
    sku_id: str
    spin_id: str
    name: str
    brand: str | None = None
    price_cents: int | None = None
    quantity_description: str | None = None
    image_url: str | None = None
    in_stock: bool = True


class InstamartCartItem(BaseModel):
    sku_id: str
    spin_id: str
    quantity: int
    name: str | None = None
    price_cents: int | None = None


class InstamartCart(BaseModel):
    items: list[InstamartCartItem] = Field(default_factory=list)
    total_items: int = 0
    total_cents: int = 0
    selected_address_id: str | None = None
    currency: str = "INR"


class InstamartAddToCartRequest(BaseModel):
    sku_id: str
    spin_id: str
    quantity: int = 1
    name: str | None = None
    selected_address_id: str | None = None


class InstamartStatus(BaseModel):
    connected: bool
    status: str
    mcp_endpoint: str
    message: str


def _call_swiggy_mcp(method: str, params: dict[str, Any]) -> dict[str, Any]:
    """Dispatch JSON-RPC or tool invocation to official Swiggy Instamart MCP endpoint."""
    import httpx

    if not (settings.swiggy_client_id and settings.swiggy_client_secret):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Swiggy OAuth is not connected. Owner authorization required.",
        )
    headers = {
        "Authorization": f"Bearer {settings.swiggy_client_secret}",
        "Content-Type": "application/json",
        "X-Swiggy-Client-ID": settings.swiggy_client_id,
    }
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1,
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(settings.swiggy_mcp_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Swiggy Instamart MCP error: {data['error']}",
                )
            result = data.get("result", {})
            return result if isinstance(result, dict) else {}
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Swiggy Instamart MCP request failed: {exc}",
        ) from exc


@router.get("/instamart/status", response_model=InstamartStatus)
def instamart_status(user: Annotated[User, Depends(current_user)]) -> InstamartStatus:
    has_credentials = bool(settings.swiggy_client_id and settings.swiggy_client_secret)
    return InstamartStatus(
        connected=has_credentials,
        status="READY" if has_credentials else "PENDING_SWIGGY_APPROVAL",
        mcp_endpoint=settings.swiggy_mcp_url,
        message=(
            "Swiggy Instamart MCP integration is configured."
            if has_credentials
            else (
                "Swiggy Instamart integration is pending official developer application "
                "and approval. Server OAuth credentials will be configured following approval."
            )
        ),
    )


@router.get("/instamart/addresses", response_model=list[InstamartAddress])
def instamart_addresses(user: Annotated[User, Depends(current_user)]) -> list[InstamartAddress]:
    result = _call_swiggy_mcp("get_addresses", {})
    raw_addresses = result.get("addresses", [])
    return [
        InstamartAddress(
            id=str(item.get("id")),
            label=item.get("label"),
            address_line=item.get("address_line", ""),
            latitude=item.get("latitude"),
            longitude=item.get("longitude"),
        )
        for item in raw_addresses
        if isinstance(item, dict) and "id" in item
    ]


@router.get("/instamart/search", response_model=list[InstamartProduct])
def instamart_search(
    query: str, user: Annotated[User, Depends(current_user)]
) -> list[InstamartProduct]:
    result = _call_swiggy_mcp("search_products", {"query": query})
    raw_products = result.get("products", [])
    return [
        InstamartProduct(
            sku_id=str(item.get("sku_id")),
            spin_id=str(item.get("spin_id")),
            name=str(item.get("name")),
            brand=item.get("brand"),
            price_cents=item.get("price_cents"),
            quantity_description=item.get("quantity_description"),
            image_url=item.get("image_url"),
            in_stock=bool(item.get("in_stock", True)),
        )
        for item in raw_products
        if isinstance(item, dict) and "sku_id" in item and "spin_id" in item
    ]


@router.get("/instamart/cart", response_model=InstamartCart)
def instamart_get_cart(user: Annotated[User, Depends(current_user)]) -> InstamartCart:
    result = _call_swiggy_mcp("get_cart", {})
    raw_items = result.get("items", [])
    items = [
        InstamartCartItem(
            sku_id=str(it.get("sku_id")),
            spin_id=str(it.get("spin_id")),
            quantity=int(it.get("quantity", 1)),
            name=it.get("name"),
            price_cents=it.get("price_cents"),
        )
        for it in raw_items
        if isinstance(it, dict) and "sku_id" in it
    ]
    return InstamartCart(
        items=items,
        total_items=len(items),
        total_cents=sum(it.price_cents or 0 for it in items),
        selected_address_id=result.get("selected_address_id"),
        currency=result.get("currency", "INR"),
    )


@router.post("/instamart/cart/add", response_model=InstamartCart)
def instamart_add_to_cart(
    payload: InstamartAddToCartRequest, user: Annotated[User, Depends(current_user)]
) -> InstamartCart:
    result = _call_swiggy_mcp(
        "update_cart",
        {
            "sku_id": payload.sku_id,
            "spin_id": payload.spin_id,
            "quantity": payload.quantity,
            "selected_address_id": payload.selected_address_id,
        },
    )
    raw_items = result.get("items", [])
    items = [
        InstamartCartItem(
            sku_id=str(it.get("sku_id")),
            spin_id=str(it.get("spin_id")),
            quantity=int(it.get("quantity", 1)),
            name=it.get("name"),
            price_cents=it.get("price_cents"),
        )
        for it in raw_items
        if isinstance(it, dict) and "sku_id" in it
    ]
    return InstamartCart(
        items=items,
        total_items=len(items),
        total_cents=sum(it.price_cents or 0 for it in items),
        selected_address_id=result.get("selected_address_id"),
        currency=result.get("currency", "INR"),
    )
