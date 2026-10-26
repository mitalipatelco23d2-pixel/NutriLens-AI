# NutriLens model distribution review

Status date: 2026-09-01  
Scope: `nutrilens-r3-nutrition-yolo11n-v1` PyTorch checkpoint and its ONNX
opset-17 export  
Purpose: internal engineering release gate; this is not legal advice

## Release decision

| Use | Engineering status | Release decision |
| --- | --- | --- |
| Current/proposed server inference | `LEGAL_REVIEW_REQUIRED` | **SERVER_USE: NOT CLEARED** for a proprietary public service under the evidence reviewed. Do not describe the existing operational deployment as license-cleared. Obtain an Ultralytics commercial license or have counsel approve and implement an AGPL-compliant release/source-offer plan. |
| Android APK/AAB distribution | `BLOCKED_DISTRIBUTION` | **ANDROID_DISTRIBUTION: BLOCKED**. The ONNX file must not enter app assets, a Play bundle, or a device download until the software/model and dataset questions below are resolved. |
| Browser/CDN distribution | `BLOCKED_DISTRIBUTION` | **WEB_DISTRIBUTION: BLOCKED**. The ONNX file must not be placed in public static assets, a CDN, or a downloadable URL. |
| Attribution | `ATTRIBUTION_REQUIRED` | **ATTRIBUTION: REQUIRED** for any redistribution of the Open Food Facts training material, with a license link and change indication. Whether the trained weights themselves are an adaptation of the image dataset is not clearly established by the reviewed materials and remains `LEGAL_REVIEW_REQUIRED`. |
| Source availability | `SOURCE_OBLIGATION` | Ultralytics' published guidance says use of its code, pretrained models, or fine-tuned models requires either making the entire project available under AGPL-3.0 or obtaining an Enterprise License. GNU AGPL section 13 independently requires a modified covered network program to offer its corresponding source to remote users. The precise boundary of the covered/combined work must be confirmed by counsel. |

The safe product path is therefore Android ML Kit OCR plus the governed client
evidence contract, with server fallback. The custom YOLO ONNX artifact remains
an evaluated, unbundled beta candidate.

## A–J distribution evidence matrix

| Area | Evidence reviewed | Engineering conclusion |
| --- | --- | --- |
| A. Ultralytics software/runtime | Installed `ultralytics==8.4.116` metadata, training script API use, official Ultralytics license pages, GNU AGPL-3.0 text | AGPL/source obligations are implicated; proprietary clearance is not established. `LEGAL_REVIEW_REQUIRED`. |
| B. Original YOLO checkpoint | Registry records an Ultralytics YOLO11n pretrained checkpoint as the base | The base checkpoint is not a clean-room NutriLens artifact. Ultralytics expressly discusses pretrained/custom-trained models. `LEGAL_REVIEW_REQUIRED`. |
| C. Custom weight ownership | NutriLens ran and recorded the fine-tune, frozen manifests, parameters and checksums | NutriLens authorship of training choices does not erase upstream checkpoint/runtime or dataset rights. Exclusive redistribution rights are not proven. |
| D. Training dataset licenses | `OFF-R3-NUTRITION-TABLE-DETECTION`, revision `d59d…`, 1,206 images/1,259 boxes; dataset record says CC BY-SA 3.0 | Attribution and license/change notices are required for redistribution of licensed material; weight-treatment questions remain for counsel. |
| E. Annotation ownership | The acquired dataset contains 1,259 source-provided detection annotations, but the repository has no individual annotator assignment or separate annotation license beyond the dataset record | Do not infer exclusive ownership of boxes. Ask the dataset publisher/counsel whether the declared CC BY-SA license covers annotations and downstream weight use. |
| F. Model export implications | Static ONNX opset 17 was exported from the fine-tuned checkpoint; hashes and parity are recorded | Export changes format, not provenance or obligations. Technical equivalence is not legal clearance. |
| G. ONNX redistribution | Manifest keeps `bundled_in_app=false`, `public_download=false`, and `BLOCKED_PENDING_LICENSE_AND_IP_REVIEW` | No public release archive, CDN, repository asset, APK or AAB may contain the ONNX file. |
| H. Android bundling | APK dependency/asset inspection and release build gate reject `.onnx`, `.pt`, `.pth`, and `.tflite` files | `BLOCKED_DISTRIBUTION` remains enforced; Android ships ML Kit OCR only. |
| I. Browser/web distribution | Web capability path has no model asset/runtime and public assets contain no export | `BLOCKED_DISTRIBUTION`; no CDN/public static model URL. |
| J. Server network service | The private worker uses the model over a network; GNU AGPL section 13 and Ultralytics' commercial guidance were reviewed | Existing server operation is not described as cleared. Obtain an Enterprise license or counsel-approved compliant source-offer/release plan before final proprietary-service sign-off. |

## Artifact identity and provenance

| Layer | Exact repository evidence | License fact | Status |
| --- | --- | --- | --- |
| Base architecture/checkpoint | `Ultralytics YOLO11n pretrained checkpoint`; Ultralytics 8.4.116 | Installed package metadata declares AGPL-3.0-or-later. Ultralytics states that its trained models, including fine-tuned models, are AGPL-3.0 by default. | `SOURCE_OBLIGATION`; `LEGAL_REVIEW_REQUIRED` for proprietary use |
| NutriLens training code | `scripts/ml/r3/train_nutrition_yolo.py` invokes the Ultralytics training API | NutriLens-authored code is separate authorship, but use/combination with the AGPL implementation and model does not itself produce proprietary clearance. | `LEGAL_REVIEW_REQUIRED` |
| Fine-tuned checkpoint | `.model-cache/r3/custom/nutrition-table-yolo11n-v1.pt`, SHA-256 `af30081551e4f9c5dfae3c6d28515ec848c2559e27c15c31e363d474d00bd16b` | Derived from the Ultralytics checkpoint/training pipeline. Ultralytics' official licensing page expressly includes custom-trained and fine-tuned models. | `SOURCE_OBLIGATION`; `BLOCKED_DISTRIBUTION` absent a compliant path |
| ONNX export | `.model-cache/r3/custom/nutrition-table-yolo11n-v1.onnx`, SHA-256 `6e65b84a391b2220107d929bcda71d7042e7896bc40ef51bda9cbf1467d2a162` | Format conversion changes representation, not provenance or license clearance. | `BLOCKED_DISTRIBUTION` |
| Training dataset | `OFF-R3-NUTRITION-TABLE-DETECTION`, source revision `d59dcee85ecb44831831a85f7b345501db2b4071`; 1,206 images, 1,259 boxes | Dataset card declares the Open Food Facts images CC BY-SA 3.0. | `ATTRIBUTION_REQUIRED`; share-alike applies to redistributed adaptations of the licensed material |
| Other R3 datasets | GroceryStore, Food-101, OFF product images and other registry entries | Registry records show separate rights restrictions. The YOLO model registry identifies only `OFF-R3-NUTRITION-TABLE-DETECTION` as this checkpoint's training dataset; other sources were evaluation/reference inputs and are not evidence of training-weight provenance. | No distribution clearance inferred; retain their existing per-dataset gates |

## Source records inspected

- `ai/model-registry/r3-models.json`
- `ai/model-registry/on-device-export-manifest.json`
- `data/external/r3/openfoodfacts/nutrition-table-detection/acquisition-summary.json`
- `data/external/r3/openfoodfacts/nutrition-table-detection/README.md`
- `data/manifests/r3-acquisitions.csv`
- `data/manifests/r3-source-artifacts.csv`
- `documentation/datasets/license-register.csv`
- `data/splits/r3_nutrition_detector_train.jsonl`
- `scripts/ml/r3/train_nutrition_yolo.py`
- installed Python distribution metadata for `ultralytics==8.4.116`

External primary sources:

- [Ultralytics licensing](https://www.ultralytics.com/license) — distinguishes
  AGPL use from proprietary/commercial use, expressly covers trained and
  fine-tuned models, and directs proprietary deployments to an Enterprise
  License.
- [Ultralytics AGPL-3.0 license text](https://www.ultralytics.com/legal/agpl-3-0-software-license)
- [GNU AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.en.html) — especially
  section 13 on modified covered software used over a network.
- [Open Food Facts nutrition-table dataset card](https://huggingface.co/datasets/openfoodfacts/nutrition-table-detection)
  — identifies the images as CC BY-SA 3.0.
- [CC BY-SA 3.0 legal code](https://creativecommons.org/licenses/by-sa/3.0/legalcode.en)
  — attribution, license notice, and share-alike terms for distributed
  adaptations.

## Questions that remain for counsel/licensor

1. Confirm whether NutriLens will obtain an Ultralytics Enterprise License or
   release the complete required project/source under an AGPL-compliant model.
2. Confirm the corresponding-source boundary for the server, mobile, and web
   combinations. Ultralytics publishes a broad interpretation; this report
   does not substitute that interpretation for legal advice.
3. Confirm whether the fine-tuned weight is an adaptation of CC BY-SA training
   images/annotations in the applicable jurisdictions. No public distribution
   should rely on an assumed answer.
4. If distribution is approved, define the exact attribution, license text,
   change notice, source offer, model notice, and downstream relinking/rebuild
   material to ship with each channel.

## Enforced repository gate

`ai/model-registry/on-device-export-manifest.json` must continue to record:

- `bundled_in_app: false`
- `public_download: false`
- `decision: BLOCKED_PENDING_LICENSE_AND_IP_REVIEW`

Do not copy the ONNX artifact from `.model-cache` into Android assets, web
public assets, release archives, or container-download endpoints until this
document is replaced by a reviewed clearance record.
