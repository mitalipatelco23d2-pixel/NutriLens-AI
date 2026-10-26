# Data Architecture

PostgreSQL is reserved for users, profiles, structured records and nutrition tracking. MongoDB is reserved for flexible scan, OCR and AI result documents. Neo4j is reserved for food, ingredient and nutrient relationships. Redis is reserved for cache, sessions, rate limiting and task coordination. FAISS is a later file-backed vector index.

R0 creates connections and storage boundaries only; it deliberately avoids premature schemas. R1 collects licensed data and R2 produces traceable processed data. Raw data is immutable, provenance is mandatory, and health data must be minimized and separated from public food reference data.
