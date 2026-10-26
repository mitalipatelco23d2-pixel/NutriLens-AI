# ADR-005 — MongoDB flexible records

**Status:** Accepted

**Context:** OCR and AI outputs evolve and contain nested documents.
**Decision:** Use MongoDB Community Edition for flexible scan documents.
**Rationale:** Natural JSON document storage and local free operation.
**Alternatives:** PostgreSQL JSONB, filesystem documents.
**Consequences:** Duplication and cross-store consistency must be controlled.
