# R1 custom collection specifications

These are collection contracts, not populated datasets. All CSVs are header-only in R1. Every
future record needs a stable ID, source/reference, version, and review status; evidence fields are
included where a claim may affect interpretation or wellness guidance.

## Common governance fields

- `source_id` and `source_url`/`source_reference`: provenance to a catalogue or consent record.
- `evidence_id`: optional link to the evidence manifest for factual or regulatory claims.
- `version`: schema/data release identifier; never silently replace prior reviewed releases.
- `review_status`: controlled future workflow such as `DRAFT`, `SOURCE_VERIFIED`, or `REVIEWED`.
- `notes`/`reviewer_notes`: limitations and review decisions, never a substitute for evidence.

## Frozen minimum templates

| Template | Domain fields and collection rule |
|---|---|
| `ingredient-synonyms.csv` | Canonical ingredient, synonym, language/script, scientific name, category. Record observed or authoritative names only. |
| `hidden-sugars.csv` | Term, canonical sugar, language, regulatory context. Do not infer a medical risk score. |
| `hidden-sodium.csv` | Term, canonical sodium source, language, regulatory context. Keep ingredient identity separate from quantity. |
| `fats-and-oils.csv` | Canonical name, synonym, type, scientific name, language. Do not add health rankings. |
| `additive-intelligence.csv` | E/INS number, functional class, jurisdiction and regulatory status. Status must be jurisdiction- and date-specific. |
| `preservative-intelligence.csv` | Names, functional class, jurisdiction and status. A preservative claim requires a cited source. |
| `allergen-mapping.csv` | Canonical allergen, observed term, language, jurisdiction and declaration class. No patient data. |
| `health-suitability-rules.csv` | Wellness context, condition, decision-support text, exclusions and clinical review. Schema only until later medical-safety review. |
| `ingredient-alternatives.csv` | Source and alternative ingredient, use context, dietary tags and limitations. Substitution is not equivalence. |
| `serving-size-knowledge.csv` | Food/state, household measure, gram weight, method, geography. Keep measured and estimated records distinguishable. |
| `density-knowledge.csv` | Food/state, density/unit, temperature, method and measured/estimated flag. Never invent missing density. |
| `multilingual-nutrition-terms.csv` | English plus all 22 scheduled Indian-language columns, scientific name and category. Empty cells are acceptable; fabricated translations are not. |
| `evidence-corpus.csv` | Bibliographic authority, access/licensing, geography and future RAG eligibility. No chunking or embedding in R1. |
| `indian-product-image-manifest.csv` | File/capture rights, product metadata, panel type, language/script, lighting, rotation, glare and low light. No image annotation in R1. |
| `indian-recipe-knowledge.csv` | Recipe/cuisine/region, servings, ingredient quantity/unit, ordered steps, times, tags, substitutes and pantry compatibility. Preserve source recipe rights. |

## Indian packaged-food and OCR capture plan

Future legally owned captures should cover multiple Indian brands and package types, with front,
ingredient, nutrition, barcode, logo, and date/expiry panels. Repeat samples should vary lighting,
rotation, glare, distance, background, blur, and low-light conditions while retaining the original
image and consent/ownership record. Faces, addresses, receipts, or location metadata must be
excluded or reviewed. R2 may create annotations; R1 does not.

OCR collection targets English and the 22 scheduled languages—Hindi, Bengali, Tamil, Telugu,
Marathi, Gujarati, Kannada, Malayalam, Punjabi, Odia, Assamese, Urdu, Sanskrit, Kashmiri,
Konkani, Nepali, Sindhi, Dogri, Manipuri, Bodo, Maithili, and Santali—where real labels are
legally obtainable. The plan does not promise equal volume or quality for every language.

## Indian recipe plan

Collect only recipes whose source permits the intended research use or whose author has granted
permission. Capture regional/cuisine context, servings, ordered ingredients with quantities and
units, ordered cooking steps, preparation/cooking times, difficulty, dietary tags, substitutions,
and pantry compatibility. Preserve the source wording and rights record in raw storage; any later
normalization or ingredient mapping is R2 work.
