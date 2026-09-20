"""Typed contracts shared by the local retriever and hosted RAG generator."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CorpusSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=500)
    organization: str = Field(min_length=1, max_length=200)
    canonical_url: str = Field(pattern=r"^https://")
    jurisdiction: str = Field(min_length=2, max_length=20)
    publication_date: str | None = None
    revision_date: str | None = None
    effective_date: str | None = None
    review_after: str
    topics: list[str] = Field(min_length=1, max_length=30)
    license_name: str = Field(min_length=1, max_length=300)
    license_url: str = Field(pattern=r"^https://")
    redistribution_mode: str
    verified_on: str
    extracted_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CorpusPassage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(pattern=r"^[a-z0-9_-]{8,80}$")
    doc_id: str
    text: str = Field(min_length=20, max_length=12_000)
    page: int | None = Field(default=None, ge=1)
    heading: str | None = Field(default=None, max_length=500)
    chunk_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RetrievedPassage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_id: str = Field(pattern=r"^S[1-9][0-9]*$")
    score: float = Field(gt=0)
    matched_terms: list[str]
    source: CorpusSource
    passage: CorpusPassage


class GeneratedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=800)
    citation_ids: list[str] = Field(min_length=1, max_length=4)
    evidence_excerpts: dict[str, str]

    @field_validator("citation_ids")
    @classmethod
    def citations_must_be_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("citation_ids must be unique")
        return values


class GeneratedExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=2_000)
    claims: list[GeneratedClaim] = Field(min_length=1, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=8)


class RagGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_facts: dict[str, Any]
    passages: list[RetrievedPassage] = Field(min_length=1, max_length=10)


class RagGenerator(Protocol):
    provider: str
    model_id: str

    def generate(self, request: RagGenerationRequest) -> GeneratedExplanation: ...
