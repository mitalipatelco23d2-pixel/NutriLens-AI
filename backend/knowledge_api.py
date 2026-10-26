"""Governed R5 food-knowledge lookup without unsupported health inference."""

from __future__ import annotations

import gzip
import json
import logging
import re
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ai.food_understanding.store import ScanNotFoundError
from ai.ingredient_intelligence.taxonomy import normalize_lookup_text
from ai.rag.semantic_retrieval import (
    SemanticDocument,
    SemanticRetriever,
    SemanticRuntimeUnavailable,
    SentenceBertEncoder,
    load_semantic_retriever,
)
from backend.auth import User, current_user
from backend.r3_api import get_owned_scan_result
from backend.r4_api import get_r4_service
from backend.settings import settings

router = APIRouter(prefix="/api/v1/knowledge", tags=["Food Knowledge"])
logger = logging.getLogger(__name__)


class KnowledgeReference(BaseModel):
    evidence_id: str
    title: str
    authority: str
    url: str
    use: str


class KnowledgeRecord(BaseModel):
    state: Literal["MATCHED", "UNKNOWN"]
    record_type: Literal["INGREDIENT", "ADDITIVE", "ALLERGEN", "UNKNOWN"]
    taxonomy_id: str | None = None
    canonical_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    parent_ids: list[str] = Field(default_factory=list)
    external_code: str | None = None
    functional_category: str | None = None
    source_dataset: str | None = None
    source_version: str | None = None
    foodon_ids: list[str] = Field(default_factory=list)
    foodon_match_method: str | None = None
    references: list[KnowledgeReference] = Field(default_factory=list)
    caution: str = (
        "Taxonomy identity and regulatory references do not by themselves establish health risk."
    )


class KnowledgeSearchResponse(BaseModel):
    query: str
    matches: list[KnowledgeRecord]
    method: str = "GOVERNED_EXACT_OR_PREFIX_V1"


class RetrievedKnowledge(BaseModel):
    record: KnowledgeRecord
    score: float = Field(ge=0, le=1)
    matched_terms: list[str]


class KnowledgeRetrievalResponse(BaseModel):
    query: str
    matches: list[RetrievedKnowledge]
    method: str = "GOVERNED_LEXICAL_RETRIEVAL_V1"


class AuthorizedKnowledgeRetrievalResponse(BaseModel):
    query: str
    matches: list[RetrievedKnowledge]
    method: Literal[
        "GOVERNED_SENTENCE_BERT_FAISS_V1",
        "GOVERNED_LEXICAL_RETRIEVAL_V1",
    ]
    semantic_state: Literal["READY_LOCAL_ONLY", "DISABLED", "UNAVAILABLE"]
    limitation: str = (
        "Retrieval ranks governed records and preserves their citations. Similarity does not "
        "establish a health effect, diagnosis, product composition, or nutritional equivalence."
    )


class KnowledgeGraphNode(BaseModel):
    id: str
    kind: Literal["PRODUCT", "INGREDIENT", "ADDITIVE", "ALLERGEN", "NUTRIENT"]
    label: str
    properties: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    source_dataset: str | None = None
    source_version: str | None = None


class KnowledgeGraphEdge(BaseModel):
    id: str
    source: str
    target: str
    relation: Literal[
        "CONTAINS_INGREDIENT",
        "HAS_ADDITIVE",
        "HAS_ALLERGEN_SIGNAL",
        "HAS_LABEL_NUTRIENT",
    ]
    evidence: str


class ScanKnowledgeGraph(BaseModel):
    scan_id: str
    nodes: list[KnowledgeGraphNode]
    edges: list[KnowledgeGraphEdge]
    method: str = "OBSERVED_SCAN_KNOWLEDGE_GRAPH_V1"
    limitation: str = (
        "Edges represent observed or taxonomy-resolved label evidence; they do not establish "
        "causal health effects or complete product composition."
    )


class HealthEffectRecord(BaseModel):
    nutrient_id: str
    names: list[str]
    role_summary: str
    authority: str
    title: str
    url: str
    dataset_version: str
    evidence_state: Literal["REFERENCE_ROLE"] = "REFERENCE_ROLE"
    caution: str = (
        "General nutrient-role reference only; not a diagnosis, intake target, treatment, "
        "or product-specific health claim."
    )


class HealthEffectSearchResponse(BaseModel):
    query: str
    matches: list[HealthEffectRecord]
    method: str = "CURATED_PRIMARY_AUTHORITY_REFERENCE_ROLES_V1"


class AlternativeIngredientMapping(BaseModel):
    ingredient: str
    alternatives: list[str]
    function: str
    limitation: str
    source: str
    source_version: str


class RetrievedAlternativeIngredient(BaseModel):
    mapping: AlternativeIngredientMapping
    score: float = Field(ge=0, le=1)
    matched_terms: list[str]


class AlternativeIngredientSearchResponse(BaseModel):
    query: str
    matches: list[RetrievedAlternativeIngredient]
    method: str = "CURATED_FUNCTIONAL_SUBSTITUTION_LEXICAL_RETRIEVAL_V1"
    limitation: str = (
        "Mappings describe a cooking function only. Alternatives can differ in texture, "
        "flavour, allergens and nutrients and are not nutritionally equivalent."
    )


FSSAI_LABEL = KnowledgeReference(
    evidence_id="EVD-FSSAI-LABEL",
    title="Food Safety and Standards (Labelling and Display) Regulations",
    authority="FSSAI",
    url="https://www.fssai.gov.in/food-law/regulations",
    use="Primary India label-law reference; the Gazette and current amendments prevail.",
)
FSSAI_ADDITIVES = KnowledgeReference(
    evidence_id="EVD-FSSAI-ADDITIVES",
    title="Food Products Standards and Food Additives Regulations",
    authority="FSSAI",
    url="https://www.fssai.gov.in/cms/compendium-fss-fps-fa.php",
    use="Primary India additive-law reference; no safety conclusion is inferred from listing.",
)
FOODON_ONTOLOGY = KnowledgeReference(
    evidence_id="EVD-FOODON-ONTOLOGY",
    title="FoodOn food ontology",
    authority="Food Ontology Consortium / OBO Foundry",
    url="https://foodon.org/",
    use=(
        "CC BY 4.0 ontology identifier linked by exact normalized label; lexical identity "
        "does not prove complete semantic equivalence."
    ),
)

_QUERY_TOKEN = re.compile(r"[a-z0-9]+")
_STOP_WORDS = frozenset(
    {
        "a",
        "about",
        "an",
        "and",
        "are",
        "can",
        "does",
        "explain",
        "for",
        "in",
        "is",
        "it",
        "me",
        "of",
        "the",
        "to",
        "what",
    }
)


@lru_cache(maxsize=1)
def _records() -> tuple[KnowledgeRecord, ...]:
    service = get_r4_service()
    foodon_links = _foodon_links()
    records: list[KnowledgeRecord] = []
    for ingredient_entry in service.ingredient_entries:
        links = foodon_links.get(ingredient_entry.taxonomy_id, [])
        records.append(
            KnowledgeRecord(
                state="MATCHED",
                record_type="INGREDIENT",
                taxonomy_id=ingredient_entry.taxonomy_id,
                canonical_name=ingredient_entry.canonical_name,
                aliases=list(
                    dict.fromkeys(
                        (*ingredient_entry.english_names, *ingredient_entry.english_synonyms)
                    )
                ),
                parent_ids=list(ingredient_entry.parent_ids),
                source_dataset=ingredient_entry.source_dataset,
                source_version=ingredient_entry.source_version,
                foodon_ids=[str(link["uri"]) for link in links],
                foodon_match_method=("EXACT_NORMALIZED_LABEL" if links else None),
                references=[FSSAI_LABEL, *([FOODON_ONTOLOGY] if links else [])],
            )
        )
    for additive_entry in service.additive_entries:
        records.append(
            KnowledgeRecord(
                state="MATCHED",
                record_type="ADDITIVE",
                taxonomy_id=additive_entry.taxonomy_id,
                canonical_name=additive_entry.canonical_name,
                aliases=list(
                    dict.fromkeys((*additive_entry.english_names, *additive_entry.english_synonyms))
                ),
                parent_ids=list(additive_entry.parent_ids),
                external_code=additive_entry.external_code,
                functional_category=additive_entry.functional_category,
                source_dataset=additive_entry.source_dataset,
                source_version=additive_entry.source_version,
                references=[FSSAI_ADDITIVES],
            )
        )
    for allergen_entry in service.allergen_entries:
        records.append(
            KnowledgeRecord(
                state="MATCHED",
                record_type="ALLERGEN",
                taxonomy_id=allergen_entry.taxonomy_id,
                canonical_name=allergen_entry.canonical_name,
                aliases=list(
                    dict.fromkeys((*allergen_entry.english_names, *allergen_entry.english_synonyms))
                ),
                parent_ids=list(allergen_entry.parent_ids),
                source_dataset=allergen_entry.source_dataset,
                source_version=allergen_entry.source_version,
                references=[FSSAI_LABEL],
            )
        )
    return tuple(records)


@lru_cache(maxsize=1)
def _foodon_links() -> dict[str, list[dict[str, str]]]:
    with gzip.open(
        Path("data/runtime/foodon-links-v0.1.0.json.gz"), "rt", encoding="utf-8"
    ) as handle:
        bundle = json.load(handle)
    return {
        str(mapping["taxonomy_id"]): [
            {str(key): str(value) for key, value in match.items()}
            for match in mapping["foodon_matches"]
        ]
        for mapping in bundle["mappings"]
    }


@lru_cache(maxsize=1)
def _alternative_ingredient_mappings() -> tuple[AlternativeIngredientMapping, ...]:
    bundle = json.loads(
        Path("data/runtime/recipe-templates-v0.2.0.json").read_text(encoding="utf-8")
    )
    return tuple(
        AlternativeIngredientMapping(
            ingredient=str(item["ingredient"]),
            alternatives=[str(value) for value in item["alternatives"]],
            function=str(item["function"]),
            limitation=str(item["limitation"]),
            source=str(bundle["source"]),
            source_version=str(bundle["schema_version"]),
        )
        for item in bundle["substitutions"]
    )


def retrieve_alternative_ingredients(
    query: str, limit: int = 10
) -> list[RetrievedAlternativeIngredient]:
    normalized_query = normalize_lookup_text(query)
    query_terms = set(_QUERY_TOKEN.findall(normalized_query))
    if not query_terms:
        return []
    matches: list[RetrievedAlternativeIngredient] = []
    for mapping in _alternative_ingredient_mappings():
        values = [mapping.ingredient, *mapping.alternatives]
        normalized_values = [normalize_lookup_text(value) for value in values]
        value_terms = {
            token for value in normalized_values for token in _QUERY_TOKEN.findall(value)
        }
        matched_terms = sorted(query_terms & value_terms)
        exact = normalized_query in normalized_values
        prefix = any(value.startswith(normalized_query) for value in normalized_values)
        if not exact and not prefix and not matched_terms:
            continue
        coverage = len(matched_terms) / len(query_terms)
        matches.append(
            RetrievedAlternativeIngredient(
                mapping=mapping,
                score=(
                    1.0 if exact else 0.85 if prefix else round(min(0.95, 0.65 + coverage * 0.3), 4)
                ),
                matched_terms=matched_terms,
            )
        )
    matches.sort(key=lambda item: (-item.score, item.mapping.ingredient))
    return matches[: max(1, min(limit, 20))]


@router.get("/search", response_model=KnowledgeSearchResponse)
def search_knowledge(
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=10, ge=1, le=25),
) -> KnowledgeSearchResponse:
    query = normalize_lookup_text(q)
    exact: list[KnowledgeRecord] = []
    prefixes: list[KnowledgeRecord] = []
    for record in _records():
        values = [
            record.canonical_name or "",
            record.external_code or "",
            *record.aliases,
            *record.foodon_ids,
            *(identifier.rsplit("/", 1)[-1] for identifier in record.foodon_ids),
        ]
        normalized = [normalize_lookup_text(value) for value in values if value]
        if query in normalized:
            exact.append(record)
        elif any(value.startswith(query) for value in normalized):
            prefixes.append(record)
    return KnowledgeSearchResponse(query=q, matches=(exact + prefixes)[:limit])


@router.get("/substitutions", response_model=AlternativeIngredientSearchResponse)
def search_alternative_ingredients(
    q: str = Query(min_length=2, max_length=120),
    limit: int = Query(default=10, ge=1, le=20),
) -> AlternativeIngredientSearchResponse:
    return AlternativeIngredientSearchResponse(
        query=q,
        matches=retrieve_alternative_ingredients(q, limit),
    )


def retrieve_knowledge(query: str, limit: int = 5) -> list[RetrievedKnowledge]:
    """Rank governed taxonomy records for a natural-language query.

    This deliberately remains lexical and auditable. It is not presented as semantic
    embedding retrieval or as evidence for a health-effect conclusion.
    """

    normalized_query = normalize_lookup_text(query)
    query_terms = {
        token
        for token in _QUERY_TOKEN.findall(normalized_query)
        if token not in _STOP_WORDS and (len(token) > 1 or token[0].isdigit())
    }
    if not query_terms:
        return []

    ranked: list[RetrievedKnowledge] = []
    for record in _records():
        values = [
            record.canonical_name or "",
            record.external_code or "",
            *record.aliases,
            *record.foodon_ids,
            *(identifier.rsplit("/", 1)[-1] for identifier in record.foodon_ids),
        ]
        normalized_values = [normalize_lookup_text(value) for value in values if value]
        record_terms = {
            token for value in normalized_values for token in _QUERY_TOKEN.findall(value)
        }
        matched_terms = sorted(query_terms & record_terms)
        exact = normalized_query in normalized_values
        if not exact and not matched_terms:
            continue
        coverage = len(matched_terms) / len(query_terms)
        score = 1.0 if exact else round(min(0.95, 0.65 + (coverage * 0.3)), 4)
        ranked.append(RetrievedKnowledge(record=record, score=score, matched_terms=matched_terms))
    ranked.sort(
        key=lambda item: (
            -item.score,
            item.record.canonical_name or "",
            item.record.taxonomy_id or "",
        )
    )
    return ranked[: max(1, min(limit, 10))]


@lru_cache(maxsize=1)
def semantic_knowledge_documents() -> tuple[SemanticDocument, ...]:
    documents: list[SemanticDocument] = []
    for record in _records():
        if not record.taxonomy_id or not record.canonical_name:
            continue
        parts = [
            f"type: {record.record_type.casefold()}",
            f"name: {record.canonical_name}",
        ]
        if record.aliases:
            parts.append(f"aliases: {', '.join(record.aliases)}")
        if record.external_code:
            parts.append(f"code: {record.external_code}")
        if record.functional_category:
            parts.append(f"function: {record.functional_category}")
        documents.append(
            SemanticDocument(
                document_id=record.taxonomy_id,
                text="; ".join(parts),
                source_dataset=record.source_dataset or "unknown",
                source_version=record.source_version or "unknown",
                reference_ids=tuple(reference.evidence_id for reference in record.references),
            )
        )
    return tuple(documents)


@lru_cache(maxsize=1)
def get_semantic_knowledge_retriever() -> SemanticRetriever:
    if not settings.semantic_rag_enabled:
        raise SemanticRuntimeUnavailable("Semantic retrieval is disabled by configuration.")
    encoder = SentenceBertEncoder(Path(settings.semantic_rag_model_path))
    return load_semantic_retriever(
        semantic_knowledge_documents(),
        encoder,
        Path(settings.semantic_rag_index_dir),
        expected_model_id=settings.semantic_rag_model_id,
    )


def retrieve_knowledge_semantic(query: str, limit: int = 5) -> list[RetrievedKnowledge]:
    retriever = get_semantic_knowledge_retriever()
    records_by_id = {
        record.taxonomy_id: record for record in _records() if record.taxonomy_id is not None
    }
    matches: list[RetrievedKnowledge] = []
    for hit in retriever.retrieve(
        query,
        limit=max(1, min(limit, 10)),
        min_score=settings.semantic_rag_min_score,
    ):
        record = records_by_id.get(hit.document.document_id)
        if record is None:
            continue
        matches.append(RetrievedKnowledge(record=record, score=hit.score, matched_terms=[]))
    return matches


@router.get("/retrieve", response_model=KnowledgeRetrievalResponse)
def retrieve_knowledge_route(
    q: str = Query(min_length=1, max_length=500),
    limit: int = Query(default=5, ge=1, le=10),
) -> KnowledgeRetrievalResponse:
    return KnowledgeRetrievalResponse(query=q, matches=retrieve_knowledge(q, limit))


@router.get("/retrieve/authorized", response_model=AuthorizedKnowledgeRetrievalResponse)
def retrieve_authorized_knowledge_route(
    user: Annotated[User, Depends(current_user)],
    q: str = Query(min_length=1, max_length=500),
    limit: int = Query(default=5, ge=1, le=10),
) -> AuthorizedKnowledgeRetrievalResponse:
    """Use semantic retrieval when locally validated, with a deterministic lexical fallback."""

    del user  # Authentication is the authorization boundary; no client identity enters retrieval.
    if settings.semantic_rag_enabled:
        try:
            return AuthorizedKnowledgeRetrievalResponse(
                query=q,
                matches=retrieve_knowledge_semantic(q, limit),
                method="GOVERNED_SENTENCE_BERT_FAISS_V1",
                semantic_state="READY_LOCAL_ONLY",
            )
        except (SemanticRuntimeUnavailable, RuntimeError) as exc:
            logger.warning("semantic_rag_fallback reason=%s", type(exc).__name__)
            semantic_state: Literal["DISABLED", "UNAVAILABLE"] = "UNAVAILABLE"
    else:
        semantic_state = "DISABLED"
    return AuthorizedKnowledgeRetrievalResponse(
        query=q,
        matches=retrieve_knowledge(q, limit),
        method="GOVERNED_LEXICAL_RETRIEVAL_V1",
        semantic_state=semantic_state,
    )


@router.get("/records/{taxonomy_id:path}", response_model=KnowledgeRecord)
def get_knowledge_record(taxonomy_id: str) -> KnowledgeRecord:
    for record in _records():
        if record.taxonomy_id == taxonomy_id:
            return record
    raise HTTPException(status_code=404, detail="Knowledge record not found.")


@lru_cache(maxsize=1)
def _health_effect_records() -> tuple[HealthEffectRecord, ...]:
    bundle = json.loads(
        Path("data/runtime/knowledge-effects-v0.1.0.json").read_text(encoding="utf-8")
    )
    version = str(bundle["dataset_version"])
    return tuple(
        HealthEffectRecord.model_validate({**record, "dataset_version": version})
        for record in bundle["records"]
    )


@router.get("/effects", response_model=HealthEffectSearchResponse)
def search_health_effect_references(
    q: str = Query(min_length=1, max_length=120),
) -> HealthEffectSearchResponse:
    """Return general primary-authority nutrient roles without personal inference."""

    return HealthEffectSearchResponse(query=q, matches=retrieve_health_effects(q))


def retrieve_health_effects(query: str) -> list[HealthEffectRecord]:
    """Match only governed nutrient names or identifiers, ranking specific matches highest."""
    cleaned = re.sub(r"[^\w\s-]", " ", query).strip()
    normalized = normalize_lookup_text(cleaned)
    padded_query = f" {normalized} "
    scored: list[tuple[int, HealthEffectRecord]] = []
    for record in _health_effect_records():
        names = {
            normalize_lookup_text(re.sub(r"[^\w\s-]", " ", record.nutrient_id).strip()),
            *(
                normalize_lookup_text(re.sub(r"[^\w\s-]", " ", name).strip())
                for name in record.names
            ),
        }
        best_len = 0
        for name in names:
            if not name:
                continue
            if name == normalized:
                best_len = max(best_len, len(name) + 100)
            elif f" {name} " in padded_query:
                best_len = max(best_len, len(name))
        if best_len > 0:
            scored.append((best_len, record))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [record for _, record in scored][:3]


@router.get("/scans/{scan_id}/graph", response_model=ScanKnowledgeGraph)
def get_scan_knowledge_graph(
    scan_id: str,
    user: Annotated[User, Depends(current_user)],
) -> ScanKnowledgeGraph:
    """Build a bounded graph from owner-scoped observed scan evidence."""

    try:
        scan = get_owned_scan_result(scan_id, user)
    except ScanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Scan not found.") from exc
    intelligence = get_r4_service().analyze(scan.ingredients, scan.nutrition)
    return _scan_graph(scan_id, scan, intelligence)


def _scan_graph(scan_id: str, scan: Any, intelligence: Any) -> ScanKnowledgeGraph:
    product_id = f"scan:{scan_id}"
    candidates = getattr(scan, "product_name_candidates", [])
    product_label = candidates[0].value if candidates else "Scanned food"
    nodes: dict[str, KnowledgeGraphNode] = {
        product_id: KnowledgeGraphNode(
            id=product_id,
            kind="PRODUCT",
            label=product_label,
            properties={"scan_id": scan_id, "evidence_state": "OBSERVED"},
        )
    }
    edges: dict[str, KnowledgeGraphEdge] = {}

    def add_resolution(
        item: Any,
        resolution: Any,
        *,
        kind: Literal["INGREDIENT", "ADDITIVE", "ALLERGEN"],
        relation: Literal["CONTAINS_INGREDIENT", "HAS_ADDITIVE", "HAS_ALLERGEN_SIGNAL"],
    ) -> None:
        ingredient = item.ingredient
        taxonomy_id = getattr(resolution, "taxonomy_id", None)
        label = getattr(resolution, "canonical_name", None) or ingredient.normalized_text
        node_id = taxonomy_id or _graph_id(kind.casefold(), ingredient.normalized_text)
        nodes[node_id] = KnowledgeGraphNode(
            id=node_id,
            kind=kind,
            label=label,
            properties={
                "original_text": ingredient.original_text,
                "matched": bool(getattr(resolution, "matched", False)),
                "match_method": str(getattr(resolution, "match_method", "NONE")),
            },
            source_dataset=getattr(resolution, "source_dataset", None),
            source_version=getattr(resolution, "source_version", None),
        )
        edge_id = f"{relation}:{product_id}:{node_id}"
        edges[edge_id] = KnowledgeGraphEdge(
            id=edge_id,
            source=product_id,
            target=node_id,
            relation=relation,
            evidence=ingredient.original_text,
        )

    for match in intelligence.ingredient_matches[:150]:
        add_resolution(
            match,
            match.taxonomy,
            kind="INGREDIENT",
            relation="CONTAINS_INGREDIENT",
        )
    for match in intelligence.additives[:75]:
        if match.additive.matched:
            add_resolution(match, match.additive, kind="ADDITIVE", relation="HAS_ADDITIVE")
    for match in intelligence.allergens[:75]:
        if match.allergen.matched:
            add_resolution(
                match,
                match.allergen,
                kind="ALLERGEN",
                relation="HAS_ALLERGEN_SIGNAL",
            )
    for row in intelligence.nutrition.rows[:50]:
        normalized_label = normalize_lookup_text(row.label) or "unknown"
        node_id = _graph_id("nutrient", normalized_label)
        nodes[node_id] = KnowledgeGraphNode(
            id=node_id,
            kind="NUTRIENT",
            label=row.label,
            properties={
                "values": " | ".join(row.values),
                "units": " | ".join(row.units),
                "basis": intelligence.nutrition.basis,
                "evidence_state": intelligence.nutrition.state,
            },
            source_dataset="R3_LABEL_EXTRACTION",
            source_version=str(getattr(scan, "contract_version", "3.0.0")),
        )
        edge_id = f"HAS_LABEL_NUTRIENT:{product_id}:{node_id}"
        edges[edge_id] = KnowledgeGraphEdge(
            id=edge_id,
            source=product_id,
            target=node_id,
            relation="HAS_LABEL_NUTRIENT",
            evidence=f"{row.label}: {' | '.join(row.values)} {' | '.join(row.units)}".strip(),
        )
    return ScanKnowledgeGraph(
        scan_id=scan_id,
        nodes=list(nodes.values())[:251],
        edges=list(edges.values())[:250],
    )


def _graph_id(kind: str, value: str) -> str:
    digest = sha256(f"{kind}:{normalize_lookup_text(value)}".encode()).hexdigest()[:20]
    return f"{kind}:{digest}"
