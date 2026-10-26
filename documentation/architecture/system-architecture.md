# System Architecture

NutriLens X has exactly 15 frozen modules. R0 establishes integration boundaries; later AI and data components shown below are planned, not complete.

```mermaid
flowchart TD
  Mobile["Flutter mobile app"] --> API["FastAPI backend"]
  Web["Next.js web app"] --> API
  API --> PG["PostgreSQL"]
  API --> Mongo["MongoDB"]
  API --> Neo["Neo4j"]
  API --> Redis["Redis"]
  API -. "R15 planned" .-> FAISS["FAISS local index"]
  API -. "R3–R13 planned" .-> AI["Hybrid AI pipelines"]
```

The root directory currently hosts the working web application to preserve existing imports. `apps/web` records its logical monorepo location; `apps/mobile` contains the Flutter foundation. The API owns connectivity and exposes explicit health state. Databases use named local Docker volumes.
