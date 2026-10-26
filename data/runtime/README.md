# Runtime data

`r4-taxonomies-v0.1.0.json.gz` is a deterministic compact derivative of the governed R2 Open Food Facts taxonomy artifacts. It contains only fields required by R4, preserves source dataset/version identifiers, and embeds SHA-256 checksums of each full source artifact. Rebuild it with `python scripts/build_r4_runtime_bundle.py`; do not hand-edit it.

`knowledge-effects-v0.1.0.json` is a small versioned R5 reference-role catalogue derived from primary WHO and NIH Office of Dietary Supplements pages recorded in `documentation/datasets/evidence-corpus-manifest.csv`. It stores citation metadata and short audited paraphrases only—no copied full text, diagnosis rules, personal intake targets or product health claims. Changes require source review, test updates and a dataset-version bump.

`foodon-links-v0.1.0.json.gz` is a deterministic compact R5 derivative linking 1,249 R4 runtime
ingredient concepts to FoodOn URIs by exact normalized English or untagged labels. It retains no
more than five ambiguous FoodOn matches per ingredient and explicitly does not claim complete
semantic equivalence. Rebuild it from the checksummed R2 full FoodOn node table and R4 runtime
bundle with `python scripts/build_foodon_runtime_links.py`; do not hand-edit it.

`faostat-country-indicators-v0.1.0.json.gz` is a deterministic R12 derivative of the pinned
FAOSTAT Food Balances Grand Total extract. It retains M49 country codes, years, three supply
indicators and all non-empty source flags, plus source revision, raw checksum, citation, terms and
limitations. It supports descriptive comparisons only: supply availability is not individual
intake and the product does not rank country health. Rebuild with
`python scripts/build_faostat_country_runtime.py`; CI verifies it with `--check`.
