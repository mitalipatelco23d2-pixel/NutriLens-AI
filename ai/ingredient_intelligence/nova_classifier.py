"""Transparent NOVA classification helpers for R4."""

from __future__ import annotations

from ai.ingredient_intelligence.schemas import (
    NovaClassification,
    NovaEvidence,
    ParsedIngredient,
)
from ai.ingredient_intelligence.taxonomy import (
    NovaTaxonomyEntry,
    get_nova_group,
)

ULTRA_PROCESSED_MARKERS = {
    "maltodextrin",
    "modified starch",
    "hydrogenated oil",
    "protein isolate",
    "flavour enhancer",
    "flavor enhancer",
    "artificial flavour",
    "artificial flavor",
    "artificial sweetener",
    "emulsifier",
    "stabilizer",
    "stabiliser",
}


def classify_nova_from_ingredients(
    ingredients: list[ParsedIngredient],
    nova_entries: list[NovaTaxonomyEntry],
) -> NovaClassification:
    """Classify NOVA only when transparent ingredient evidence supports it."""

    evidence: list[NovaEvidence] = []

    for ingredient in ingredients:
        value = ingredient.normalized_text

        for marker in ULTRA_PROCESSED_MARKERS:
            if marker in value:
                evidence.append(
                    NovaEvidence(
                        ingredient_text=ingredient.original_text,
                        evidence_type="ULTRA_PROCESSED_MARKER",
                        evidence_value=marker,
                        source="R4_RULESET",
                    )
                )

    if evidence:
        group = get_nova_group(nova_entries, 4)

        if group is None:
            return NovaClassification(
                classification_method="UNKNOWN",
                evidence=evidence,
                warnings=[
                    "NOVA 4 evidence was detected, but the governed taxonomy record "
                    "was unavailable."
                ],
            )

        return NovaClassification(
            group_number=4,
            taxonomy_id=group.taxonomy_id,
            canonical_name=group.canonical_name,
            confidence=1.0,
            classification_method="RULE_EVIDENCE",
            evidence=evidence,
            source_dataset=group.source_dataset,
            source_version=group.source_version,
        )

    return NovaClassification(
        classification_method="UNKNOWN",
        warnings=["Insufficient ingredient evidence for a defensible NOVA classification."],
    )
