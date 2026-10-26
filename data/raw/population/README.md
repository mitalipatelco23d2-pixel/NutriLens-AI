# Raw population data

Aggregate public statistics may be stored here. R1 excludes individual-level personal data.

`faostat-fbs-grand-total-v2025-10-16.csv.gz` is the canonical, sorted Grand Total extract from the
official FAOSTAT Food Balances query endpoint. It contains national annual food-energy, protein and
fat supply indicators and their source flags for the pinned 2010–2023 release. It is public
aggregate data, not personal data and not measured individual intake. Refresh and rebuild with
`python scripts/build_faostat_country_runtime.py --refresh`; ordinary CI runs only `--check` and do
not contact the network.
