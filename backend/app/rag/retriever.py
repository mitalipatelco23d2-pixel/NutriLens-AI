"""Deterministic local BM25 retrieval over verified corpus passages."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any

from ..nlp.ingredients import ingredient_quality_from_result, trusted_ingredients
from .corpus import LoadedCorpus
from .models import RetrievedPassage


TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")
QUERY_FIELD_LIMIT = 80
QUERY_LIST_LIMIT = 24


def tokenize(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return TOKEN_PATTERN.findall(normalized)


def _bounded_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value[:QUERY_LIST_LIMIT]:
        if isinstance(item, str):
            cleaned = " ".join(item.split())[:QUERY_FIELD_LIMIT]
            if cleaned:
                output.append(cleaned)
    return output


def build_retrieval_query(
    nlp_result: dict[str, Any],
    health_result: dict[str, Any] | None,
) -> str:
    """Build a bounded lexical query; raw OCR and free-form instructions are excluded."""
    parts: list[str] = []
    ingredient_quality, _ = ingredient_quality_from_result(nlp_result)
    ingredients = trusted_ingredients(nlp_result)
    parts.extend(_bounded_strings(ingredients))
    if ingredient_quality == "trusted":
        parts.extend(_bounded_strings(nlp_result.get("additives")))
    parts.extend(_bounded_strings(nlp_result.get("allergens")))
    basis = str(nlp_result.get("basis") or "unknown")[:24]
    parts.extend(["food label", basis])
    if ingredient_quality == "trusted":
        parts.append("ingredient declaration")

    nutrition = nlp_result.get("nutrition")
    if isinstance(nutrition, dict):
        supported = {
            "sugars_100g": "sugar",
            "sodium_100g": "sodium salt",
            "trans_fat_100g": "trans fat",
            "saturated_fat_100g": "saturated fat",
        }
        for key, label in supported.items():
            if key in nutrition:
                parts.append(label)

    health = health_result if isinstance(health_result, dict) else {}
    nutrition_score = health.get("nutrition_score")
    if isinstance(nutrition_score, dict):
        parts.extend(_bounded_strings(nutrition_score.get("reasons")))
    return " ".join(parts)[:2_000]


class BM25Retriever:
    """Small-corpus Okapi BM25 implementation with deterministic tie-breaking."""

    def __init__(
        self,
        corpus: LoadedCorpus,
        *,
        top_k: int = 6,
        min_score: float = 1.0,
        max_per_source: int = 2,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.corpus = corpus
        self.top_k = top_k
        self.min_score = min_score
        self.max_per_source = max_per_source
        self.k1 = k1
        self.b = b
        self._tokens = [tokenize(item.text) for item in corpus.passages]
        self._frequencies = [Counter(tokens) for tokens in self._tokens]
        self._average_length = max(
            1.0, sum(len(tokens) for tokens in self._tokens) / len(self._tokens)
        )
        document_frequency: Counter[str] = Counter()
        for tokens in self._tokens:
            document_frequency.update(set(tokens))
        total = len(self._tokens)
        self._idf = {
            term: math.log(1.0 + (total - count + 0.5) / (count + 0.5))
            for term, count in document_frequency.items()
        }

    def search(self, query: str) -> list[RetrievedPassage]:
        query_terms = list(dict.fromkeys(tokenize(query)))
        if not query_terms:
            return []
        scored: list[tuple[float, str, int, list[str]]] = []
        for index, (tokens, frequencies) in enumerate(
            zip(self._tokens, self._frequencies, strict=True)
        ):
            score = 0.0
            matched: list[str] = []
            length_ratio = len(tokens) / self._average_length
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                matched.append(term)
                denominator = frequency + self.k1 * (1 - self.b + self.b * length_ratio)
                score += self._idf.get(term, 0.0) * (
                    frequency * (self.k1 + 1) / denominator
                )
            passage = self.corpus.passages[index]
            if score >= self.min_score and matched:
                scored.append((score, passage.chunk_id, index, matched))
        scored.sort(key=lambda item: (-item[0], item[1]))

        selected: list[RetrievedPassage] = []
        per_source: Counter[str] = Counter()
        for score, _, index, matched in scored:
            passage = self.corpus.passages[index]
            if per_source[passage.doc_id] >= self.max_per_source:
                continue
            per_source[passage.doc_id] += 1
            selected.append(
                RetrievedPassage(
                    citation_id=f"S{len(selected) + 1}",
                    score=round(score, 6),
                    matched_terms=matched,
                    source=self.corpus.sources[passage.doc_id],
                    passage=passage,
                )
            )
            if len(selected) >= self.top_k:
                break
        return selected
