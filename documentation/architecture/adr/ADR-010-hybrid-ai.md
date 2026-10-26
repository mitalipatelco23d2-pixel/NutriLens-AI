# ADR-010 — Hybrid AI architecture

**Status:** Accepted as future architecture

**Context:** Nutrition guidance needs both pattern recognition and auditable rules/evidence.
**Decision:** Combine vision/OCR, deterministic parsing, rules, graphs, retrieval, trained ranking models and optional grounded language generation.
**Rationale:** No single model provides the required accuracy, traceability and safety.
**Alternatives:** End-to-end LLM, rules-only, model-only.
**Consequences:** Integration and evaluation are more complex; R0 includes no claim that these pipelines are implemented.
