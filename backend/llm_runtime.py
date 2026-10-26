"""Bounded internal LLM provider abstraction with deterministic failure fallback."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from backend.settings import Settings, settings


@dataclass(frozen=True)
class GenerationResult:
    text: str | None
    mode: str


def generate_assistant_answer(
    *,
    question: str,
    evidence: list[str],
    deterministic_answer: str,
    config: Settings = settings,
) -> GenerationResult:
    """Synthesize only supplied evidence; never turn provider failure into an API failure."""

    if config.llm_provider == "none":
        return GenerationResult(text=None, mode="DETERMINISTIC_FALLBACK")
    if (
        config.llm_provider != "ollama"
        or not config.llm_base_url
        or not config.llm_model
        or not config.llm_service_token
    ):
        return GenerationResult(text=None, mode="DEGRADED_NOT_CONFIGURED")

    bounded_question = question.strip()[:2_000]
    bounded_evidence = [item.strip()[:500] for item in evidence[:20] if item.strip()]
    prompt = (
        "You are NutriLens X. Answer only from the supplied governed evidence. "
        "Do not diagnose, invent facts, or omit uncertainty. Keep the answer under 180 words.\n\n"
        f"Question: {bounded_question}\n"
        f"Evidence: {bounded_evidence or ['No additional evidence retrieved.']}\n"
        f"Deterministic fallback: {deterministic_answer[:1_500]}"
    )
    headers = {
        "Authorization": f"Bearer {config.llm_service_token}",
        "Content-Type": "application/json",
    }
    try:
        if config.llm_provider == "ollama":
            response = httpx.post(
                f"{config.llm_base_url.rstrip('/')}/api/chat",
                headers=headers,
                json={
                    "model": config.llm_model,
                    "stream": False,
                    "messages": [{"role": "user", "content": prompt}],
                    "options": {"num_predict": 256, "temperature": 0.1},
                },
                timeout=config.llm_timeout_seconds,
            )
            response.raise_for_status()
            content = response.json().get("message", {}).get("content")
        else:
            response = httpx.post(
                f"{config.llm_base_url.rstrip('/')}/v1/chat/completions",
                headers=headers,
                json={
                    "model": config.llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 256,
                    "temperature": 0.1,
                },
                timeout=config.llm_timeout_seconds,
            )
            response.raise_for_status()
            content = response.json().get("choices", [{}])[0].get("message", {}).get("content")
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return GenerationResult(text=None, mode="DEGRADED_PROVIDER_UNAVAILABLE")
    text = str(content).strip() if content else ""
    return GenerationResult(
        text=text[:4_000] if text else None,
        mode="LLM_SYNTHESIS" if text else "DEGRADED_EMPTY_RESPONSE",
    )
