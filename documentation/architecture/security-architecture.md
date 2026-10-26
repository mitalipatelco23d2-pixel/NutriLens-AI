# Security Architecture Outline

R0 uses environment-based secrets, ignored local files, dependency auditing, input validation, least-information health responses and non-sensitive logs. Future R16 work will add authentication, authorization, token rotation, consent, deletion, encryption strategy, threat modelling, rate limits and security monitoring.

Trust boundaries exist between clients and API, API and databases, imported datasets and processing pipelines, and AI output and user-facing guidance. Neither client is trusted to enforce authorization. AI text is untrusted output and must be grounded, bounded and filtered before presentation.
