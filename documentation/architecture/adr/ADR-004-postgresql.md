# ADR-004 — PostgreSQL structured data

**Status:** Accepted

**Context:** Users, profiles and nutrition records require transactions and constraints.
**Decision:** Use PostgreSQL for structured application data.
**Rationale:** Mature relational integrity and open-source tooling.
**Alternatives:** MySQL, SQLite.
**Consequences:** Schema migrations and relational ownership must be maintained.
