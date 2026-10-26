"""R4 Ingredient Intelligence service."""

from __future__ import annotations

import re

from ai.food_understanding.schemas import IngredientExtraction, NutritionExtraction
from ai.ingredient_intelligence.additive_resolver import AdditiveResolver
from ai.ingredient_intelligence.allergen_resolver import AllergenResolver
from ai.ingredient_intelligence.input_adapter import parse_r3_ingredients
from ai.ingredient_intelligence.nova_classifier import (
    classify_nova_from_ingredients,
)
from ai.ingredient_intelligence.parser import parse_ingredient_list
from ai.ingredient_intelligence.resolver import IngredientResolver
from ai.ingredient_intelligence.schemas import (
    AllergenMatch,
    IngredientAllergenResolution,
    IngredientComplexity,
    NutritionContext,
    NutritionEvidenceRow,
    ParsedIngredient,
    R4IngredientIntelligenceResult,
    ResultConfidence,
)
from ai.ingredient_intelligence.signals import (
    detect_additive_function_signal,
    detect_hidden_sugars_from_taxonomy,
    detect_ingredient_ancestry_signal,
)
from ai.ingredient_intelligence.taxonomy import (
    AdditiveTaxonomyEntry,
    AllergenTaxonomyEntry,
    IngredientTaxonomyEntry,
    NovaTaxonomyEntry,
)

_QUALIFIED_ALLERGEN_STATEMENT = re.compile(
    r"\b(?:may|might|could|no|not|neither|without|except|absent)\b|"
    r"\b(?:doesn['’]t|don['’]t)\b|\btraces?\s+of\b|"
    r"\bfree[\s-]+(?:from|of)\b|\b\w+[\s-]+free\b|"
    r"\b(?:facility|equipment|factory)\b",
    re.I,
)
_AFFIRMATIVE_ALLERGEN_PREFIX = re.compile(
    r"^\s*(?:contains?|all?ergens?(?:\s+information)?)\b\s*(?:[:\-]\s*)*", re.I
)


def _explicit_allergen_resolutions(
    raw_statement: str, resolver: AllergenResolver
) -> tuple[list[IngredientAllergenResolution], list[str]]:
    """Only an unqualified declaration can establish explicit positive evidence.

    The current contract has no modality. Keep mixed, precautionary, negative,
    oversized and legacy unlabelled statements unresolved with their raw source.
    In particular, splitting 'may contain milk, soy' into ingredients is unsafe.
    """
    statement = raw_statement.strip()
    if not statement:
        return [], []
    prefix = _AFFIRMATIVE_ALLERGEN_PREFIX.match(statement)
    qualified = bool(_QUALIFIED_ALLERGEN_STATEMENT.search(statement))
    if qualified or prefix is None or len(statement) > 2_000:
        method = "UNRESOLVED_QUALIFIED_STATEMENT" if qualified else "UNRESOLVED_STATEMENT"
        return [
            IngredientAllergenResolution(
                ingredient=ParsedIngredient(
                    original_text=statement,
                    normalized_text=statement.casefold(),
                    position=1,
                ),
                allergen=AllergenMatch(
                    matched=False,
                    match_method=method,
                    evidence_source="PACKAGE_ALLERGEN_STATEMENT_OCR",
                    evidence_text=raw_statement,
                ),
            )
        ], ["Package allergen statement requires review; it is not affirmative presence evidence."]
    # Remove only governed leading headings, never words from inside a qualifier.
    explicit_text = statement
    for _ in range(3):
        explicit_text, replacements = _AFFIRMATIVE_ALLERGEN_PREFIX.subn("", explicit_text, count=1)
        if not replacements:
            break
    explicit_text = re.sub(r"\s+(?:and|&)\s+", ", ", explicit_text, flags=re.I)
    resolutions = resolver.resolve_many(parse_ingredient_list(explicit_text).ingredients[:32])
    return [
        resolution.model_copy(
            update={
                "allergen": resolution.allergen.model_copy(
                    update={
                        "match_method": (
                            "EXPLICIT_STATEMENT"
                            if resolution.allergen.matched
                            else "UNRESOLVED_STATEMENT"
                        ),
                        "evidence_source": "PACKAGE_ALLERGEN_STATEMENT_OCR",
                        "evidence_text": raw_statement,
                    }
                )
            }
        )
        for resolution in resolutions
    ], []


class IngredientIntelligenceService:
    """Orchestrate R4 analysis from governed R3 ingredient output."""

    def __init__(
        self,
        ingredient_entries: list[IngredientTaxonomyEntry],
        additive_entries: list[AdditiveTaxonomyEntry],
        allergen_entries: list[AllergenTaxonomyEntry],
        nova_entries: list[NovaTaxonomyEntry],
    ) -> None:
        self.ingredient_entries = ingredient_entries
        self.additive_entries = additive_entries
        self.allergen_entries = allergen_entries
        self.nova_entries = nova_entries

        self.ingredient_resolver = IngredientResolver(ingredient_entries)
        self.additive_resolver = AdditiveResolver(additive_entries)
        self.allergen_resolver = AllergenResolver(allergen_entries)

    def analyze(
        self,
        extraction: IngredientExtraction,
        nutrition: NutritionExtraction | None = None,
    ) -> R4IngredientIntelligenceResult:
        """Run the current governed R4 pipeline."""

        parsed = parse_r3_ingredients(extraction)

        ingredients = parsed.ingredients

        ingredient_matches = self.ingredient_resolver.resolve_many(ingredients)
        additives = self.additive_resolver.resolve_many(ingredients)
        allergens = [
            resolution.model_copy(
                update={
                    "allergen": resolution.allergen.model_copy(
                        update={
                            "evidence_source": "INGREDIENT_TAXONOMY",
                            "evidence_text": resolution.ingredient.original_text,
                        }
                    )
                }
            )
            for resolution in self.allergen_resolver.resolve_many(ingredients)
        ]
        allergen_warnings: list[str] = []
        if extraction.allergen_text:
            explicit_resolutions, allergen_warnings = _explicit_allergen_resolutions(
                extraction.allergen_text, self.allergen_resolver
            )
            for resolution in explicit_resolutions:
                if not resolution.allergen.matched:
                    allergens.append(resolution)
                    continue
                taxonomy_id = resolution.allergen.taxonomy_id
                duplicate_index = next(
                    (
                        index
                        for index, current in enumerate(allergens)
                        if current.allergen.matched and current.allergen.taxonomy_id == taxonomy_id
                    ),
                    None,
                )
                if duplicate_index is None:
                    allergens.append(resolution)
                else:
                    allergens[duplicate_index] = resolution
        resolved_count = sum(item.taxonomy.matched for item in ingredient_matches)
        unresolved_count = len(ingredients) - resolved_count
        additive_count = sum(item.additive.matched for item in additives)
        ratio = resolved_count / len(ingredients) if ingredients else 0.0
        sources = sorted(
            {
                item.taxonomy.source_dataset
                for item in ingredient_matches
                if item.taxonomy.source_dataset
            }
        )

        return R4IngredientIntelligenceResult(
            parse=parsed,
            ingredient_matches=ingredient_matches,
            additives=additives,
            allergens=allergens,
            hidden_sugars=detect_hidden_sugars_from_taxonomy(
                ingredients,
                self.ingredient_entries,
            ),
            sodium_sources=detect_ingredient_ancestry_signal(
                ingredients,
                self.ingredient_entries,
                ancestor_ids={"off:ingredient:salt"},
                category="SODIUM_SOURCE",
            ),
            oils_and_fats=detect_ingredient_ancestry_signal(
                ingredients,
                self.ingredient_entries,
                ancestor_ids={"off:ingredient:oil-and-fat", "off:ingredient:fat"},
                category="OIL_OR_FAT_SOURCE",
            ),
            sweeteners=detect_additive_function_signal(
                ingredients,
                self.additive_entries,
                functions={"sweetener"},
                category="SWEETENER",
            ),
            preservatives=detect_additive_function_signal(
                ingredients,
                self.additive_entries,
                functions={"preservative"},
                category="PRESERVATIVE",
            ),
            nova=classify_nova_from_ingredients(
                ingredients,
                self.nova_entries,
            ),
            complexity=IngredientComplexity(
                ingredient_count=len(ingredients),
                compound_ingredient_count=sum(item.depth > 0 for item in ingredients),
                additive_count=additive_count,
                unresolved_count=unresolved_count,
                level=_complexity_level(len(ingredients), additive_count),
            ),
            confidence=ResultConfidence(
                score=round(ratio, 3),
                state=_confidence_state(len(ingredients), ratio),
                resolved_ingredient_ratio=round(ratio, 3),
                source_datasets=sources,
            ),
            nutrition=_nutrition_context(nutrition),
            warnings=allergen_warnings,
        )


def _complexity_level(ingredient_count: int, additive_count: int) -> str:
    if ingredient_count == 0:
        return "UNKNOWN"
    if ingredient_count <= 5 and additive_count == 0:
        return "LOW"
    if ingredient_count <= 12 and additive_count <= 2:
        return "MODERATE"
    return "HIGH"


def _confidence_state(ingredient_count: int, ratio: float) -> str:
    if ingredient_count == 0:
        return "UNKNOWN"
    if ratio >= 0.8:
        return "HIGH"
    if ratio >= 0.5:
        return "MODERATE"
    return "LOW"


def _nutrition_context(nutrition: NutritionExtraction | None) -> NutritionContext:
    if nutrition is None or not nutrition.table_rows:
        return NutritionContext(
            extraction_confidence=nutrition.confidence if nutrition else None,
            basis=nutrition.basis if nutrition else "UNKNOWN",
            state="UNKNOWN",
        )
    return NutritionContext(
        basis=nutrition.basis,
        rows=[
            NutritionEvidenceRow(label=row.label, values=row.values, units=row.units)
            for row in nutrition.table_rows
        ],
        extraction_confidence=nutrition.confidence,
        state="AVAILABLE",
    )
