from __future__ import annotations

import json
import struct
import zipfile
from pathlib import Path

from scripts.data_engineering.density import process_density
from scripts.data_engineering.foodon import process_foodon
from scripts.data_engineering.images import duplicate_checksums, inspect_image
from scripts.data_engineering.io_utils import (
    read_jsonl,
    sha256_file,
    snapshot_checksums,
    verify_unchanged,
)
from scripts.data_engineering.off_taxonomy import parse_taxonomy
from scripts.data_engineering.quarantine import Quarantine
from scripts.data_engineering.schemas import NutritionRecord, TaxonomyRecord
from scripts.data_engineering.source_registry import SourceInfo
from scripts.data_engineering.usda import process_usda


def source(path: Path, dataset_id: str) -> SourceInfo:
    return SourceInfo(
        dataset_id=dataset_id,
        path=path,
        checksum=sha256_file(path),
        version="TEST_FIXTURE_ONLY",
        source_url="https://example.invalid/test-only",
        license_status="TEST_FIXTURE_ONLY",
    )


def test_off_taxonomy_parser_preserves_languages_and_codes(tmp_path: Path) -> None:
    taxonomy = tmp_path / "taxonomy.txt"
    taxonomy.write_text(
        "en: E 330 - Citric acid, citric acid\nhi: परीक्षण नाम\n"
        "additives_classes:en: en:acidity-regulator\n\n"
        "< en: E 330 - Citric acid\nen: E 331 - Sodium citrates\n",
        encoding="utf-8",
    )
    quarantine = Quarantine("OFF-TAX-ADDITIVES")
    records = list(
        parse_taxonomy(
            source(taxonomy, "OFF-TAX-ADDITIVES"),
            "additive",
            quarantine=quarantine,
        )
    )
    assert len(records) == 2
    assert records[0].external_code == "E330"
    assert records[0].functional_category == "acidity-regulator"
    assert {item.language for item in records[0].localized_names} == {"en", "hi"}
    TaxonomyRecord.model_validate(records[0].model_dump())
    assert records[1].parent_ids == [records[0].taxonomy_id]


def _usda_zip(path: Path) -> None:
    root = "fixture/"
    files = {
        "foundation_food.csv": '"fdc_id","NDB_number","footnote"\n"1","1",""\n',
        "food_category.csv": '"id","code","description"\n"1","0000","Software fixtures"\n',
        "measure_unit.csv": '"id","name"\n"1000","fixture unit"\n',
        "food.csv": (
            '"fdc_id","data_type","description","food_category_id","publication_date"\n'
            '"1","foundation_food","SOFTWARE FIXTURE - NOT REAL FOOD","1","2026-01-01"\n'
        ),
        "nutrient.csv": (
            '"id","name","unit_name","nutrient_nbr","rank"\n'
            '"1003","Protein","G","203","600"\n'
            '"1093","Sodium, Na","MG","307","5800"\n'
        ),
        "food_nutrient.csv": (
            '"id","fdc_id","nutrient_id","amount","data_points","derivation_id","min","max","median","footnote","min_year_acquired"\n'
            '"10","1","1003","1","1","","","","","",""\n'
            '"11","1","1093","400","1","","","","","",""\n'
            '"12","1","1003","-1","1","","","","","",""\n'
        ),
        "food_portion.csv": (
            '"id","fdc_id","seq_num","amount","measure_unit_id","portion_description","modifier","gram_weight","data_points","footnote","min_year_acquired"\n'
            '"20","1","1","1","1000","test portion","","50","1","",""\n'
        ),
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(root + name, content)


def test_usda_parser_maps_nutrients_and_quarantines_invalid(tmp_path: Path) -> None:
    archive = tmp_path / "usda.zip"
    _usda_zip(archive)
    stats = process_usda(
        source(archive, "USDA-FOUNDATION"),
        tmp_path / "interim",
        tmp_path / "processed",
        tmp_path / "quarantine",
    )
    assert stats["foods"] == 1
    assert stats["nutrition"] == 1
    assert stats["quarantined"] == 1
    record = next(read_jsonl(tmp_path / "processed/usda_nutrition.jsonl"))
    parsed = NutritionRecord.model_validate(record)
    assert parsed.protein_g is not None and parsed.protein_g.normalized_value == 1
    assert parsed.salt_g is not None and parsed.salt_g.normalized_value == 1


def test_foodon_parser_extracts_nodes_synonyms_and_edges(tmp_path: Path) -> None:
    owl = tmp_path / "foodon.owl"
    owl.write_text(
        '<?xml version="1.0"?><rdf:RDF '
        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#" '
        'xmlns:owl="http://www.w3.org/2002/07/owl#" '
        'xmlns:obo="http://www.geneontology.org/formats/oboInOwl#">'
        '<owl:Class rdf:about="urn:food:1"><rdfs:label xml:lang="en">Fixture node</rdfs:label>'
        '<obo:hasExactSynonym xml:lang="en">Test synonym</obo:hasExactSynonym>'
        '<rdfs:subClassOf rdf:resource="urn:food:0"/></owl:Class></rdf:RDF>',
        encoding="utf-8",
    )
    stats = process_foodon(source(owl, "FOODON"), tmp_path / "out", tmp_path / "q")
    assert stats == {"nodes": 1, "edges": 1, "missing_labels": 0, "quarantined": 0}
    node = next(read_jsonl(tmp_path / "out/foodon_nodes.jsonl"))
    assert node["synonyms"][0]["text"] == "Test synonym"


def _density_xlsx(path: Path) -> None:
    workbook = (
        '<?xml version="1.0"?><workbook '
        'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Density DB" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels = (
        '<?xml version="1.0"?><Relationships '
        'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    sheet = (
        '<?xml version="1.0"?><worksheet '
        'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>"
        '<row r="1">'
        '<c r="A1" t="inlineStr"><is><t>Food</t></is></c>'
        '<c r="B1" t="inlineStr"><is><t>Density</t></is></c>'
        "</row>"
        '<row r="2"><c r="A2" t="inlineStr"><is><t>Fixture category</t></is></c></row>'
        '<row r="3">'
        '<c r="A3" t="inlineStr"><is><t>Fixture item</t></is></c>'
        '<c r="B3"><v>1.25</v></c>'
        '<c r="D3" t="inlineStr"><is><t>TEST</t></is></c>'
        "</row>"
        "</sheetData></worksheet>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


def test_density_parser_retains_category_and_measurement_rows(tmp_path: Path) -> None:
    xlsx = tmp_path / "density.xlsx"
    _density_xlsx(xlsx)
    stats = process_density(source(xlsx, "FAO-DENSITY"), tmp_path / "out", tmp_path / "q")
    assert stats["output_records"] == 2
    assert stats["measurements"] == 1
    assert stats["category_headers"] == 1


def test_image_validation_and_duplicate_checksums(tmp_path: Path) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", 2, 3) + b"\x00" * 8
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    empty = tmp_path / "empty.png"
    first.write_bytes(png)
    second.write_bytes(png)
    empty.write_bytes(b"")
    inspections = [inspect_image(path) for path in (first, second, empty)]
    assert inspections[0].valid and (inspections[0].width, inspections[0].height) == (2, 3)
    assert inspections[2].failure_reason == "ZERO_BYTE_FILE"
    assert len(duplicate_checksums(inspections)) == 1


def test_checksum_snapshot_detects_raw_change(tmp_path: Path) -> None:
    raw = tmp_path / "raw.txt"
    raw.write_text("original", encoding="utf-8")
    snapshot = snapshot_checksums([raw])
    verify_unchanged(snapshot)
    raw.write_text("modified", encoding="utf-8")
    try:
        verify_unchanged(snapshot)
    except RuntimeError as exc:
        assert "immutable source changed" in str(exc)
    else:
        raise AssertionError("raw change was not detected")


def test_quarantine_record_keeps_reason_and_source_snapshot(tmp_path: Path) -> None:
    quarantine = Quarantine("TEST")
    quarantine.add(
        source_record_id="1",
        stage="VALIDATE",
        rule="INVALID_UNIT",
        reason="fixture failure",
        snapshot={"unit": "made-up"},
    )
    assert quarantine.write(tmp_path / "q.jsonl") == 1
    row = json.loads((tmp_path / "q.jsonl").read_text(encoding="utf-8"))
    assert row["validation_rule"] == "INVALID_UNIT"
