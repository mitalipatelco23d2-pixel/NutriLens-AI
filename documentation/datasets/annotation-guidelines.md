# R2 annotation guidelines

These rules govern later rights-cleared image annotation. R2 currently has zero eligible source
images and therefore zero detection, meal, and OCR annotations. No boxes or transcriptions are
invented to demonstrate the formats.

## General rules

- Confirm rights/consent and manifest linkage before annotation. Annotate only visible evidence.
- Coordinates use the original image pixel space: top-left `x,y`, positive `width,height`. Boxes
  must stay inside the image and tightly enclose the visible target, including only minimal margin.
- One physical instance gets one annotation ID. Overlapping valid objects get separate boxes.
- Mark `annotation_source` and `review_status`; a second reviewer resolves ambiguous labels.
- Partially visible/occluded targets are annotated only when their identity and boundary are
  reasonably inferable from visible pixels. Note truncation/occlusion; exclude unidentifiable slivers.
- Glare, blur, perspective, or low resolution is not repaired in labels. Exclude a region when a
  reviewer cannot identify its class or faithfully transcribe it.

## Packaged-food classes

| Label | Inclusion rule | Important exclusions |
|---|---|---|
| `product` | The complete visible retail package | Shelf/hand/background; separate packages get separate boxes |
| `nutrition_table` | Full bordered or clearly grouped nutrition declaration | Isolated front-of-pack calorie badges |
| `ingredient_list` | Heading and complete visible ingredient paragraph | Marketing copy and preparation directions |
| `barcode` | Entire linear barcode, including quiet zones when visible | Price stripes and decorative lines |
| `qr_code` | Complete QR symbol | Other square graphics |
| `brand_logo` | Tight visible brand mark | Generic certification/quality marks |
| `expiry_or_date_region` | Printed/stamped manufacture, best-before, use-by, batch/date block | Unrelated numbers |

Truncated panels may be boxed when their region type is certain, with review status noting
truncation. A nutrition table containing ingredient text does not receive an ingredient box unless
the ingredient region is spatially distinct. Overlap is allowed when a child region genuinely lies
within the product box.

## Meals

- `food_item`: each visually separable edible component; do not guess hidden ingredients.
- `plate_or_container`: the eating/serving vessel, not the surrounding table.
- `reference_object`: only a deliberately placed, dimension-known calibration object. Never label
  ordinary cutlery or hands as scale references.
- Mixed dishes that cannot be visually separated receive one `food_item` box and a neutral note;
  annotators must not infer recipe composition.

## OCR regions

- Create a region for a coherent line/block according to the downstream annotation protocol;
  transcribe visible characters exactly, preserving spelling, punctuation, numbers, and script.
- Record BCP-47-compatible source language. Mixed-script text uses the predominant language plus a
  note; do not translate, transliterate, or expand abbreviations.
- Use an empty transcription only when the source format explicitly represents illegible text;
  otherwise exclude and flag the region for review.
- Preserve line breaks when the protocol requires block transcription. Mark glare, curved surface,
  low resolution, cut-off characters, and uncertain glyphs in review metadata.

YOLO import/export covers detection class IDs and normalized boxes; COCO conversion preserves image,
category, annotation IDs, and pixel boxes. OCR transcriptions remain in canonical JSON rather than
being forced into YOLO. Duplicate image checksums must not cross dataset splits.
