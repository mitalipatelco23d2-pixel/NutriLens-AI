# Pre-R1 dataset audit

Audit performed on 2026-08-08 before R1 modifications.

- `data/` contained only the R0 boundary directories (`raw`, `external`, `interim`, `processed`,
  and `annotations`) and placeholder README files.
- `documentation/` contained the R0 architecture, security, development, and project-management
  material but no dataset catalogue, license register, module matrix, evidence manifest, or gap
  report.
- `scripts/` contained R0 verification/capability tooling but no acquisition/checksum utility.
- `databases/` contained service setup only; no populated food graph or vector index.
- `ai/` and `reports/` contained no dataset payloads or R1 manifests.
- No existing datasets, sample files, custom dictionaries, dataset licenses, or download manifests
  were found, so R1 duplicated none.
- The only non-generated project file at or above 1 MiB was an ignored local tool cache artifact;
  no accidental large dataset was present or tracked.

R0 working files and architecture were preserved. R1 adds collection/governance boundaries only.
