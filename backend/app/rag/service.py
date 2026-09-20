"""Optional source-backed retrieval-augmented explanation service."""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from .corpus import CorpusUnavailableError, LoadedCorpus
from .generator import RagGenerationError
from .models import GeneratedExplanation, RagGenerationRequest, RagGenerator, RetrievedPassage
from .retriever import BM25Retriever, build_retrieval_query


UNSUPPORTED_MEDICAL_PATTERNS = (
    re.compile(r"\b(?:cures?|treats?|prevents?)\b", re.IGNORECASE),
    re.compile(r"\b(?:safe|unsafe)\s+(?:ingredient|to consume|for consumption)\b", re.IGNORECASE),
    re.compile(r"\b(?:will|definitely)\s+cause\b", re.IGNORECASE),
    re.compile(r"\b(?:cancer|diabetes|heart disease)\s+risk\b", re.IGNORECASE),
)


def _bounded_text_list(value: Any, *, limit: int = 24, width: int = 100) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        " ".join(item.split())[:width]
        for item in value[:limit]
        if isinstance(item, str) and item.strip()
    ]


def _product_facts(
    nlp_result: dict[str, Any],
    health_result: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return only bounded analysis fields approved for hosted generation."""
    nutrition = nlp_result.get("nutrition")
    safe_nutrition: dict[str, float] = {}
    if isinstance(nutrition, dict):
        for key in (
            "energy_kj_100g",
            "energy_kcal_100g",
            "sugars_100g",
            "saturated_fat_100g",
            "trans_fat_100g",
            "sodium_100g",
            "salt_100g",
        ):
            value = nutrition.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                safe_nutrition[key] = float(value)

    health = health_result if isinstance(health_result, dict) else {}
    score = health.get("nutrition_score")
    score = score if isinstance(score, dict) else {}
    risk = health.get("ingredient_risk")
    risk = risk if isinstance(risk, dict) else {}
    probabilities = risk.get("probabilities")
    safe_probabilities = {
        str(key)[:20]: float(value)
        for key, value in (probabilities.items() if isinstance(probabilities, dict) else [])
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    return {
        "jurisdiction": "IN",
        "nutrition_basis": str(nlp_result.get("basis") or "unknown")[:24],
        "ingredients": _bounded_text_list(nlp_result.get("ingredients")),
        "additives": _bounded_text_list(nlp_result.get("additives")),
        "allergens": _bounded_text_list(nlp_result.get("allergens")),
        "nutrition": safe_nutrition,
        "existing_m2_result": {
            "status": str(health.get("status") or "unavailable")[:24],
            "health_score": health.get("health_score"),
            "score_level": health.get("score_level"),
            "nutrition_basis": score.get("basis", health.get("basis", "unknown")),
            "nutrition_reasons": _bounded_text_list(score.get("reasons"), limit=12, width=180),
            "missing_nutrients": _bounded_text_list(score.get("missing_nutrients"), limit=12),
            "ingredient_risk_label": risk.get("risk_level", health.get("risk_level")),
            "ingredient_risk_probabilities": safe_probabilities,
        },
    }


def _validate_generation(
    generated: GeneratedExplanation,
    passages: list[RetrievedPassage],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    allowed = {item.citation_id: item for item in passages}
    rendered_claims: list[dict[str, Any]] = []
    used_excerpts: dict[str, list[str]] = {}
    answer_parts: list[str] = []
    for claim in generated.claims:
        if any(pattern.search(claim.text) for pattern in UNSUPPORTED_MEDICAL_PATTERNS):
            raise RagGenerationError("Generated content contained an unsupported medical claim.")
        if set(claim.citation_ids) != set(claim.evidence_excerpts):
            raise RagGenerationError("Generated citations and evidence excerpts do not align.")
        for citation_id in claim.citation_ids:
            passage = allowed.get(citation_id)
            if passage is None:
                raise RagGenerationError("Generated content cited an unknown source passage.")
            excerpt = " ".join(claim.evidence_excerpts[citation_id].split())
            source_text = " ".join(passage.passage.text.split())
            if len(excerpt) < 8 or excerpt not in source_text:
                raise RagGenerationError("Generated evidence was not an exact source excerpt.")
            used_excerpts.setdefault(citation_id, []).append(excerpt)
        rendered_claims.append(
            {
                "text": claim.text,
                "citation_ids": claim.citation_ids,
                "evidence_excerpts": claim.evidence_excerpts,
            }
        )
        markers = "".join(f"[{item}]" for item in claim.citation_ids)
        answer_parts.append(f"{claim.text} {markers}")

    sources: list[dict[str, Any]] = []
    for item in passages:
        if item.citation_id not in used_excerpts:
            continue
        sources.append(
            {
                "citation_id": item.citation_id,
                "title": item.source.title,
                "organization": item.source.organization,
                "canonical_url": item.source.canonical_url,
                "jurisdiction": item.source.jurisdiction,
                "publication_date": item.source.publication_date,
                "revision_date": item.source.revision_date,
                "page": item.passage.page,
                "heading": item.passage.heading,
                "chunk_id": item.passage.chunk_id,
                "chunk_sha256": item.passage.chunk_sha256,
                "evidence_excerpts": list(dict.fromkeys(used_excerpts[item.citation_id])),
            }
        )
    return " ".join(answer_parts), rendered_claims, sources


class RagExplanationService:
    method = "bm25_plus_cloudflare_grounded_generation"

    def __init__(
        self,
        *,
        enabled: bool,
        corpus_dir: Path,
        jurisdiction: str,
        generator: RagGenerator | None,
        top_k: int = 6,
        min_score: float = 1.0,
        max_per_source: int = 2,
    ) -> None:
        self.enabled = enabled
        self.corpus_dir = Path(corpus_dir)
        self.jurisdiction = jurisdiction
        self.generator = generator
        self.top_k = top_k
        self.min_score = min_score
        self.max_per_source = max_per_source
        self._corpus: LoadedCorpus | None = None
        self._retriever: BM25Retriever | None = None

    def _base(self, status: str, *, reason: str, detail: str) -> dict[str, Any]:
        return {
            "status": status,
            "available": status == "available",
            "requested": self.enabled,
            "method": self.method,
            "reason": reason,
            "detail": detail,
            "generator": {
                "provider": getattr(self.generator, "provider", "cloudflare_workers_ai_rest"),
                "model": getattr(self.generator, "model_id", None),
                "live_validation_completed": bool(
                    getattr(self.generator, "live_validation_completed", False)
                ),
            },
            "retrieval": None,
            "answer": None,
            "claims": [],
            "sources": [],
            "limitations": [],
            "disclaimer": (
                "Source-grounded general food-label information; not medical advice or "
                "evidence that an ingredient caused a model prediction."
            ),
        }

    def explain(
        self,
        nlp_result: dict[str, Any],
        health_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return self._base(
                "disabled",
                reason="disabled_by_default",
                detail="Source-backed RAG is not enabled.",
            )
        if self.generator is None:
            return self._base(
                "unavailable",
                reason="generator_unavailable",
                detail="Cloudflare Workers AI credentials are unavailable.",
            )
        health_snapshot = deepcopy(health_result)
        try:
            if self._corpus is None:
                self._corpus = LoadedCorpus.load(
                    self.corpus_dir,
                    jurisdiction=self.jurisdiction,
                )
            if self._retriever is None:
                self._retriever = BM25Retriever(
                    self._corpus,
                    top_k=self.top_k,
                    min_score=self.min_score,
                    max_per_source=self.max_per_source,
                )
            query = build_retrieval_query(nlp_result, health_snapshot)
            passages = self._retriever.search(query)
            if not passages:
                result = self._base(
                    "insufficient_evidence",
                    reason="no_passage_met_reviewed_threshold",
                    detail="No current, jurisdiction-appropriate source passage met the retrieval threshold.",
                )
                result["retrieval"] = {
                    **self._corpus.public_metadata(),
                    "query_terms": sorted(set(build_retrieval_query(nlp_result, health_snapshot).split()))[:40],
                    "retrieved_count": 0,
                    "threshold": self.min_score,
                }
                return result
            request = RagGenerationRequest(
                product_facts=_product_facts(nlp_result, health_snapshot),
                passages=passages,
            )
            generated = self.generator.generate(request)
            if health_result != health_snapshot:
                raise RagGenerationError("RAG changed the existing M2 result.")
            answer, claims, sources = _validate_generation(generated, passages)
            return {
                "status": "available",
                "available": True,
                "requested": True,
                "method": self.method,
                "reason": None,
                "detail": None,
                "generator": {
                    "provider": self.generator.provider,
                    "model": self.generator.model_id,
                    "live_validation_completed": bool(
                        getattr(self.generator, "live_validation_completed", False)
                    ),
                },
                "retrieval": {
                    **self._corpus.public_metadata(),
                    "retrieved_count": len(passages),
                    "threshold": self.min_score,
                    "top_k": self.top_k,
                },
                "answer": answer,
                "claims": claims,
                "sources": sources,
                "limitations": generated.limitations,
                "disclaimer": (
                    "Source-grounded general food-label information; not medical advice or "
                    "evidence that an ingredient caused a model prediction."
                ),
            }
        except CorpusUnavailableError as exc:
            return self._base("unavailable", reason="corpus_unavailable", detail=str(exc))
        except RagGenerationError as exc:
            return self._base("unavailable", reason="generation_rejected", detail=str(exc))
        except Exception:
            return self._base(
                "unavailable",
                reason="unexpected_failure",
                detail="Source-backed RAG was unavailable.",
            )
