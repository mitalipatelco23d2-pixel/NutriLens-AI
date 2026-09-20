"""Optional source-backed retrieval-augmented generation integration."""

from __future__ import annotations

from ..core.config import Settings
from .generator import CloudflareWorkersAIGenerator
from .service import RagExplanationService


def build_rag_service(settings: Settings) -> RagExplanationService:
    generator = None
    if (
        settings.m5_rag_enabled
        and settings.cloudflare_account_id
        and settings.cloudflare_api_token
    ):
        generator = CloudflareWorkersAIGenerator(
            account_id=settings.cloudflare_account_id,
            api_token=settings.cloudflare_api_token,
            model_id=settings.cloudflare_model_id,
            timeout_seconds=settings.m5_rag_timeout_seconds,
            retries=settings.m5_rag_retries,
            max_tokens=settings.m5_rag_max_tokens,
            max_input_chars=settings.m5_rag_max_input_chars,
            concurrency=settings.m5_rag_concurrency,
            max_daily_requests=settings.m5_rag_max_daily_requests,
        )
    return RagExplanationService(
        enabled=settings.m5_rag_enabled,
        corpus_dir=settings.m5_rag_corpus_dir,
        jurisdiction=settings.m5_rag_jurisdiction,
        generator=generator,
        top_k=settings.m5_rag_top_k,
        min_score=settings.m5_rag_min_score,
        max_per_source=settings.m5_rag_max_per_source,
    )


__all__ = [
    "CloudflareWorkersAIGenerator",
    "RagExplanationService",
    "build_rag_service",
]
