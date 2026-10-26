# Deterministic split manifests

R2 split manifests use stable grouping keys and seed `20260808`. Exact/near duplicates must not
cross train, validation, and test boundaries. See `documentation/datasets/split-policy.md`.
