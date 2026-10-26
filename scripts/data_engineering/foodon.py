"""FoodOn OWL class, label, synonym, and hierarchy extraction."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from scripts.data_engineering.io_utils import atomic_text_writer
from scripts.data_engineering.normalization import validate_unicode_text
from scripts.data_engineering.quarantine import Quarantine
from scripts.data_engineering.schemas import LocalizedText, OntologyEdge, OntologyNode
from scripts.data_engineering.source_registry import SourceInfo

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
OWL = "http://www.w3.org/2002/07/owl#"
OBOINOWL = "http://www.geneontology.org/formats/oboInOwl#"


def process_foodon(
    source: SourceInfo,
    output_dir: Path,
    quarantine_dir: Path,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    node_path = output_dir / "foodon_nodes.jsonl"
    edge_path = output_dir / "foodon_edges.jsonl"
    quarantine = Quarantine(source.dataset_id)
    node_count = 0
    edge_count = 0
    missing_labels = 0
    seen: set[str] = set()
    with atomic_text_writer(node_path) as node_target, atomic_text_writer(edge_path) as edge_target:
        for _event, element in ET.iterparse(source.path, events=("end",)):
            if element.tag != f"{{{OWL}}}Class":
                continue
            uri = element.attrib.get(f"{{{RDF}}}about")
            if not uri:
                element.clear()
                continue
            if uri in seen:
                quarantine.add(
                    source_record_id=uri,
                    stage="FOODON_PARSE",
                    rule="UNIQUE_ONTOLOGY_URI",
                    reason="duplicate OWL class URI",
                    snapshot={"uri": uri},
                )
                element.clear()
                continue
            seen.add(uri)
            labels: list[LocalizedText] = []
            synonyms: list[LocalizedText] = []
            deprecated = False
            parents: list[str] = []
            for child in element:
                text = (child.text or "").strip()
                language = child.attrib.get(f"{{{RDF}}}lang", "und").lower()
                if child.tag == f"{{{RDFS}}}label" and text and validate_unicode_text(text):
                    labels.append(LocalizedText(language=language, text=text))
                elif (
                    child.tag
                    in {
                        f"{{{OBOINOWL}}}hasExactSynonym",
                        f"{{{OBOINOWL}}}hasRelatedSynonym",
                        f"{{{OBOINOWL}}}hasBroadSynonym",
                        f"{{{OBOINOWL}}}hasNarrowSynonym",
                    }
                    and text
                ):
                    synonyms.append(LocalizedText(language=language, text=text))
                elif child.tag == f"{{{RDFS}}}subClassOf":
                    parent = child.attrib.get(f"{{{RDF}}}resource")
                    if parent:
                        parents.append(parent)
                elif child.tag == f"{{{OWL}}}deprecated" and text.lower() == "true":
                    deprecated = True
            if not labels:
                missing_labels += 1
            node = OntologyNode(
                uri=uri,
                labels=labels,
                synonyms=synonyms,
                deprecated=deprecated,
                lineage=source.lineage(uri),
            )
            node_target.write(
                json.dumps(node.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n"
            )
            node_count += 1
            for parent in parents:
                edge_id = f"subclass:{uri}->{parent}"
                edge = OntologyEdge(
                    edge_id=edge_id,
                    source_uri=uri,
                    predicate="rdfs:subClassOf",
                    target_uri=parent,
                    lineage=source.lineage(edge_id),
                )
                edge_target.write(
                    json.dumps(edge.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
                    + "\n"
                )
                edge_count += 1
            element.clear()
            if limit is not None and node_count >= limit:
                break
    quarantined = quarantine.write(quarantine_dir / "foodon.jsonl")
    return {
        "nodes": node_count,
        "edges": edge_count,
        "missing_labels": missing_labels,
        "quarantined": quarantined,
    }
