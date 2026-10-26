# ADR-009 — Docker Compose local development

**Status:** Accepted

**Context:** Six services must start reproducibly for a zero-cost local project.
**Decision:** Use Docker Compose with named volumes and health checks.
**Rationale:** One documented command and isolation from host installations.
**Alternatives:** Manual installs, Kubernetes.
**Consequences:** Docker Desktop resources and image downloads are required; this is not production orchestration.
