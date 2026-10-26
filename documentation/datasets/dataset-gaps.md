# R1 dataset gaps

| Gap ID | Description | Affected module(s) | Severity | Current workaround | Future custom-data requirement | Target release |
|---|---|---:|---|---|---|---|
| GAP-001 | Too few rights-cleared Indian packaged-food images | 1, 12 | Critical | Catalogue global/retail sources; use collection manifest | Diverse Indian brands and all required panels/conditions | R3 |
| GAP-002 | No labelled Indian nutrition-table OCR benchmark | 1, 2 | Critical | Evaluate public scene-text data only | Rights-cleared multilingual labels and later annotations | R3 |
| GAP-003 | Uneven coverage across 22 scheduled Indian languages | 1, 2, 11, 14 | High | CLDR/Wikidata discovery plus empty controlled schema | Expert-reviewed food/nutrition terminology by language | R4/R17 |
| GAP-004 | Indian ingredient synonyms and spelling variants are incomplete | 2, 3 | High | OFF taxonomies and FoodOn as starting references | Reviewed regional names, transliterations, scientific links | R4 |
| GAP-005 | Product nutrition records are crowdsourced and incomplete | 1, 7, 9 | High | Retain provider provenance and missingness | Indian product verification samples | R2/R3 |
| GAP-006 | Portion/household measures are US-centric | 7, 8, 9 | High | USDA methodology and FAO references | Measured Indian utensils, foods, and serving contexts | R9/R10 |
| GAP-007 | Food density coverage is incomplete and state-dependent | 1, 8 | Medium | FAO/INFOODS plus explicit measured/estimated field | Controlled measurements by preparation state/temperature | R10 |
| GAP-008 | Indian recipe sources have fragmented rights and schemas | 8 | High | Registration/manual source catalogue | Permissioned regional recipe collection | R10 |
| GAP-009 | Additive evidence and jurisdiction status change over time | 2, 3, 5 | High | Official FSSAI/EFSA/FDA sources with version dates | Reviewed additive evidence linked by jurisdiction/release | R4/R7 |
| GAP-010 | FoodKG has no verified complete direct dump | 3 | Medium | FoodOn plus documented reconstruction route | Reproducible licensed subset after Recipe1M approval | R5 |
| GAP-011 | Health-suitability rules lack clinical validation | 4, 5, 6, 11 | Critical | Schema only; no medical rules implemented | Evidence review and qualified clinical governance | R6/R7 |
| GAP-012 | Population sources use incompatible indicators/schemas | 10 | Medium | Catalogue sources separately; aggregate only | R2 provenance-preserving harmonization plan | R12 |
| GAP-013 | Open retail datasets underrepresent Indian packaging layouts | 1 | High | Combine source diversity during later evaluation | Layout-stratified Indian capture plan | R3 |
| GAP-014 | Recipe substitutions are context-sensitive, not equivalent | 6, 8 | High | Store limitations in schema; no automatic rules | Culinary/expert-reviewed substitutions by dish/context | R8/R10 |
| GAP-015 | Some authoritative references retain restrictive copyrights | 5, 10, 11 | Medium | Link/cite and block reuse pending review | Permissions or open equivalent evidence sources | R7/R13 |
| GAP-016 | Full OFF/USDA/CV exports exceed comfortable local storage | 1, 7, 12 | Medium | Explicit large-download gate and bounded subsets | Storage budget and version-pinning policy | R15 |

No gap is concealed by synthetic values, translations, inferred licenses, or false acquisition
claims. Resolution targets identify the earliest relevant roadmap release and do not mark that
later capability as implemented.
