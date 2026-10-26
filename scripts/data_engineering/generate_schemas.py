"""Generate versioned JSON Schemas from the canonical Pydantic models."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data_engineering import SCHEMA_VERSION
from scripts.data_engineering.schemas import (
    DensityRecord,
    DetectionAnnotation,
    EvidenceDocument,
    ImageManifestRecord,
    IngredientSynonymRecord,
    NutritionRecord,
    OCRAnnotation,
    OntologyEdge,
    OntologyNode,
    PopulationRecord,
    ProductRecord,
    QuarantineRecord,
    RecipeRecord,
    ServingRecord,
    TaxonomyRecord,
)

MODELS: dict[str, type[BaseModel]] = {
    "product": ProductRecord,
    "nutrition": NutritionRecord,
    "ingredient-synonym": IngredientSynonymRecord,
    "taxonomy": TaxonomyRecord,
    "ontology-node": OntologyNode,
    "ontology-edge": OntologyEdge,
    "image-manifest": ImageManifestRecord,
    "detection-annotation": DetectionAnnotation,
    "ocr-annotation": OCRAnnotation,
    "recipe": RecipeRecord,
    "density": DensityRecord,
    "serving": ServingRecord,
    "evidence-document": EvidenceDocument,
    "population": PopulationRecord,
    "quarantine": QuarantineRecord,
}


def generate(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for name, model in MODELS.items():
        schema = model.model_json_schema()
        schema["$id"] = f"https://nutrilens.local/schemas/{SCHEMA_VERSION}/{name}.schema.json"
        schema["x-nutrilens-schema-version"] = SCHEMA_VERSION
        path = output_dir / f"{name}.schema.json"
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        outputs.append(path)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/schemas/r2-v1.0.0"))
    args = parser.parse_args()
    outputs = generate(args.output_dir)
    print(f"Generated {len(outputs)} JSON Schemas in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
