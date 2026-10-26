# ADR-001 — FastAPI backend

**Status:** Accepted

**Context:** NutriLens needs typed Python APIs close to its future AI tooling.
**Decision:** Use FastAPI with Pydantic and Uvicorn.
**Rationale:** Async-capable APIs, generated OpenAPI and strong Python integration.
**Alternatives:** Flask, Django REST Framework, Node.js.
**Consequences:** Python dependency management and explicit service boundaries are required.
