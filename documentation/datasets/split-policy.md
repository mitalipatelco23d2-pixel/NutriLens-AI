# R2 dataset split policy

The default deterministic allocation is 70% TRAIN, 15% VALIDATION, and 15% TEST with seed
`20260808`. Assignment hashes the seed and stable group ID; it is independent of input ordering and
is reproducible across machines. Ratios may be changed for a documented downstream experiment, but
never merely to improve reported results.

## Leakage boundaries

- Products/nutrition: group by stable product identity or barcode; brand/product-family grouping is
  required when variants would reveal near-identical labels across splits.
- Images/OCR: exact checksum duplicates, near-duplicate captures, crops of the same source image,
  and repeated package instances stay in one group.
- Recipes: exact and reviewed near-duplicate recipes stay together.
- Ontology/taxonomy/evidence: no train/test split is asserted in R2 because these are reference
  structures, not labelled predictive examples.
- Quarantine records are never assigned to a model split.

R2 generated a split only for the 395 available USDA Foundation food records, grouping on original
USDA `fdc_id`. It produced 281 TRAIN, 62 VALIDATION, and 52 TEST records. The validator found zero
groups appearing in more than one split. The sample run produced 137/37/26 for 200 records.

No image, OCR, product, recipe, or population split is generated because no eligible local R1
payload exists. Their policy and schema are ready without presenting synthetic fixtures as data.
