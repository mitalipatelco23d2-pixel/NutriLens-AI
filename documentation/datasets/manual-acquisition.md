# Manual, registered, restricted, and unavailable sources

These instructions prevent access controls or license uncertainty from being mistaken for missing
automation. Do not place manually acquired files locally until their terms and provenance are
recorded in the catalogue, license register, and acquisition manifest.

## Manual download required

- **FOODKG:** use the official project and GitHub repository. The obtainable artifact is code and
  graph-construction material; reconstruction requires Recipe1M files and significant storage.
  There is no verified complete official FoodKG dump in R1.
- **SKU-110K:** the GitHub repository is source code, not the image dataset. The provider-linked
  archive is approximately 13.6 GB and restricted to academic/non-commercial research. Review
  terms, acquire manually, and record its archive checksum; do not redistribute.
- **COCO-Text v2:** accept provider terms, acquire the annotation file, then obtain required MS
  COCO images separately under their own terms. Record both layers independently.
- **RecipeDB:** use the official download interface and comply with CC BY-NC-SA 3.0. Keep it
  manual because it is non-commercial and recipe/source rights need review.
- **FSSAI labelling and additives:** select the current official compendium files in a browser.
  The labelling PDF endpoint returned an HTML application shell during automated verification, so
  it is not recorded as downloaded. Treat compendia as convenient references; Gazette
  notifications and amendments prevail. FSSAI copyright is retained.

## Registration required

- **Recipe1M+:** register through the official MIT Im2Recipe site. Do not bypass access, share
  credentials, or redistribute files. Confirm source-image and research-use terms before use.
- **NFHS-5/DHS:** provider registration and project approval are required for microdata. NutriLens
  R1 needs no person-level records; prefer public aggregate reports and do not attempt automated
  ingest, linkage, re-identification, or redistribution.

## License review required

- **ICMR-NIN Dietary Guidelines 2024 and IFCT 2017:** official reference access exists, but reuse
  in an electronic product is not established; keep blocked pending written permission/review.
- **EFSA OpenFoodTox:** data access exists, but the precise reusable-data terms must be confirmed
  before acquisition or redistribution.
- **WHO Global Health Observatory:** aggregate use is intended, but the exact API/data license and
  transition state require a source-specific review before automated ingest.
- **BHASHINI/ULCA:** every contributed corpus/model may use different terms. Review a selected
  nutrition-relevant resource; the portal itself is not one universally licensed dataset.

## Unavailable

- **SynthText:** the Oxford VGG page documents the dataset and historical scale, but its official
  download is no longer available and current dataset terms are restrictive/non-transferable.
  Do not use an unverified mirror. Re-evaluate later or generate properly licensed synthetic data
  in a future release after defining a compliant pipeline.

TextOCR and GroceryStoreDataset remain `AVAILABLE`: follow their official instructions and verify
the separate image rights before acquiring. Full Open Food Facts exports and image archives are
available but storage-gated; use bounded samples or explicit large-download commands.
