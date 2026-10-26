# Dataset catalogue review guide

The machine-readable source of truth is `dataset-catalogue.csv`; the workbook in
`outputs/r1-dataset-governance/` is a filtered review copy. The catalogue currently covers all
required R1 source groups and all 15 frozen modules.

## Source-group decisions

- **Open Food Facts:** full CSV and JSONL exports remain available but not downloaded because of
  size and mutability. Seven official taxonomies are locally acquired. Image work will use a
  bounded product-ID manifest and provider-supplied image URLs rather than the global archive.
- **USDA FoodData Central:** the small April 2026 Foundation Foods CSV archive is acquired.
  Branded and FNDDS releases are documented but storage-gated. No values are normalized.
- **FoodOn and FoodKG:** the stable FoodOn OWL release is acquired. FoodKG is documented as a
  construction workflow with Recipe1M dependencies—not as a nonexistent complete dump.
- **Vision/OCR:** GroceryStoreDataset, SKU-110K, TextOCR, SynthText, and COCO-Text have distinct
  source-versus-image and license/access notes. SynthText is `UNAVAILABLE` because no current
  official download was verified.
- **Recipes:** Recipe1M+ remains registration-gated; RecipeDB is manually gated by non-commercial
  terms; Recipe Commons is a metadata/specification source whose individual books retain their
  declared licenses.
- **Scientific/regulatory:** WHO, ICMR-NIN, FSSAI, EFSA, and FDA entries are authoritative
  references. Rights-unclear ICMR and EFSA artifacts stay blocked for license review.
- **Population:** FAOSTAT and WHO GHO are aggregate sources. NFHS microdata is not ingested.
- **Serving/density:** FAO/INFOODS v2.0 is acquired as a measured/estimated reference; USDA FNDDS
  is documented for household measures. Custom templates never invent values.
- **Multilingual:** Unicode CLDR and bounded Wikidata lexeme access are legally usable supporting
  resources but are not nutrition-complete. BHASHINI resources require item-level license review.

Approximate sizes are provider descriptions observed on 2026-08-08 and may change. “Available”
means an official route exists; only a manifest-backed local file is “Downloaded.”
