# ADR-008 — Redis coordination

**Status:** Accepted

**Context:** Caching, sessions, rate limits and later task coordination need fast ephemeral state.
**Decision:** Use Redis with append-only local development persistence.
**Rationale:** Simple, open-source and widely supported.
**Alternatives:** In-process cache, database tables.
**Consequences:** Redis data cannot be the sole source of durable truth.
