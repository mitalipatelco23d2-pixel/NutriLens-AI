"""Citation-ready metadata processing for locally acquired evidence documents."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from scripts.data_engineering.io_utils import write_jsonl
from scripts.data_engineering.schemas import EvidenceDocument
from scripts.data_engineering.source_registry import SourceInfo


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def process_evidence(
    repo_root: Path,
    sources: dict[str, SourceInfo],
    output_dir: Path,
) -> dict[str, Any]:
    evidence_rows = _rows(repo_root / "documentation/datasets/evidence-corpus-manifest.csv")
    records: list[EvidenceDocument] = []
    if "WHO-HEALTHY-DIET" in sources:
        source = sources["WHO-HEALTHY-DIET"]
        evidence = next(
            row for row in evidence_rows if row["Evidence ID"] == "EVD-WHO-HEALTHY-DIET"
        )
        records.append(
            EvidenceDocument(
                document_id=evidence["Evidence ID"],
                title=evidence["Title"],
                organization=evidence["Organization/author"],
                publication_date=evidence["Publication date"] or None,
                document_type=evidence["Publication type"],
                topics=[value.strip() for value in evidence["Topic"].split(";") if value.strip()],
                language="en",
                source_url=evidence["URL"],
                local_path=source.path.relative_to(repo_root).as_posix(),
                checksum=source.checksum,
                license_access=evidence["License/access notes"],
                rag_eligibility=evidence["RAG eligibility"],
                citation_metadata={
                    "organization": evidence["Organization/author"],
                    "title": evidence["Title"],
                    "publication_date": evidence["Publication date"],
                    "access_date": evidence["Access date"],
                    "url": evidence["URL"],
                },
                text_extraction_status="NOT_PERFORMED_COPYRIGHT_AND_RAG_SCOPE_REVIEW_REQUIRED",
                lineage=source.lineage(evidence["Evidence ID"]),
            )
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    count = write_jsonl(output_dir / "evidence_documents.jsonl", records)
    return {"input_documents": count, "output_documents": count, "text_extracted": 0}
