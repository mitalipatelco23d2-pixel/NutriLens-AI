from types import SimpleNamespace

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.auth import create_session_token, user_store
from backend.main import app


def test_governed_knowledge_search_returns_provenance_and_caution() -> None:
    response = TestClient(app).get("/api/v1/knowledge/search", params={"q": "E100"})
    assert response.status_code == 200
    match = response.json()["matches"][0]
    assert match["record_type"] == "ADDITIVE"
    assert match["source_dataset"]
    assert match["references"][0]["evidence_id"] == "EVD-FSSAI-ADDITIVES"
    assert "do not by themselves establish health risk" in match["caution"]


def test_ingredient_knowledge_links_foodon_ids_with_lexical_limit() -> None:
    response = TestClient(app).get("/api/v1/knowledge/search", params={"q": "chickpea"})
    assert response.status_code == 200
    match = next(item for item in response.json()["matches"] if item["record_type"] == "INGREDIENT")
    assert "http://purl.obolibrary.org/obo/FOODON_03306811" in match["foodon_ids"]
    assert match["foodon_match_method"] == "EXACT_NORMALIZED_LABEL"
    foodon_reference = next(
        item for item in match["references"] if item["evidence_id"] == "EVD-FOODON-ONTOLOGY"
    )
    assert "does not prove complete semantic equivalence" in foodon_reference["use"]

    by_identifier = TestClient(app).get("/api/v1/knowledge/search", params={"q": "FOODON_03306811"})
    assert by_identifier.status_code == 200
    assert by_identifier.json()["matches"][0]["canonical_name"] == "chickpea"


def test_knowledge_search_is_bounded_and_unknown_is_empty() -> None:
    client = TestClient(app)
    assert client.get("/api/v1/knowledge/search", params={"q": "e", "limit": 3}).status_code == 200
    assert (
        len(client.get("/api/v1/knowledge/search", params={"q": "e", "limit": 3}).json()["matches"])
        == 3
    )
    assert (
        client.get("/api/v1/knowledge/search", params={"q": "definitely-not-real"}).json()[
            "matches"
        ]
        == []
    )


def test_knowledge_retrieval_handles_a_natural_language_question() -> None:
    response = TestClient(app).get(
        "/api/v1/knowledge/retrieve", params={"q": "What is caramel colour E100?"}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["method"] == "GOVERNED_LEXICAL_RETRIEVAL_V1"
    assert payload["matches"]
    assert payload["matches"][0]["record"]["references"]
    assert payload["matches"][0]["matched_terms"]


def test_knowledge_retrieval_does_not_invent_unknown_matches() -> None:
    response = TestClient(app).get(
        "/api/v1/knowledge/retrieve", params={"q": "Tell me about quuxylophone"}
    )
    assert response.status_code == 200
    assert response.json()["matches"] == []


def test_authorized_retrieval_requires_authentication() -> None:
    response = TestClient(app).get(
        "/api/v1/knowledge/retrieve/authorized", params={"q": "soy emulsifier"}
    )
    assert response.status_code == 401


def test_authorized_retrieval_uses_auditable_fallback_when_semantic_is_disabled() -> None:
    user = user_store.upsert_google_user(
        {
            "sub": "rag-user",
            "email": "rag@example.com",
            "email_verified": True,
            "name": "RAG User",
        }
    )
    token, _ = create_session_token(user)

    response = TestClient(app).get(
        "/api/v1/knowledge/retrieve/authorized",
        params={"q": "soy lecithin"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["method"] == "GOVERNED_LEXICAL_RETRIEVAL_V1"
    assert payload["semantic_state"] == "DISABLED"
    assert payload["matches"][0]["record"]["references"]
    assert "does not establish a health effect" in payload["limitation"]


def test_authorized_retrieval_fails_safe_when_semantic_artifact_is_invalid(
    monkeypatch: MonkeyPatch,
) -> None:
    import backend.knowledge_api as knowledge_api

    user = user_store.upsert_google_user(
        {
            "sub": "rag-fallback-user",
            "email": "rag-fallback@example.com",
            "email_verified": True,
            "name": "RAG Fallback User",
        }
    )
    token, _ = create_session_token(user)
    monkeypatch.setattr(
        knowledge_api,
        "settings",
        SimpleNamespace(semantic_rag_enabled=True),
    )

    def invalid_semantic(query: str, limit: int) -> list[object]:
        del query, limit
        raise RuntimeError("checksum mismatch")

    monkeypatch.setattr(knowledge_api, "retrieve_knowledge_semantic", invalid_semantic)

    response = TestClient(app).get(
        "/api/v1/knowledge/retrieve/authorized",
        params={"q": "soy lecithin"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["semantic_state"] == "UNAVAILABLE"
    assert response.json()["method"] == "GOVERNED_LEXICAL_RETRIEVAL_V1"


def test_scan_graph_links_only_owner_scoped_observed_evidence(monkeypatch: MonkeyPatch) -> None:
    import backend.knowledge_api as knowledge_api

    user = user_store.upsert_google_user(
        {
            "sub": "graph-user",
            "email": "graph@example.com",
            "email_verified": True,
            "name": "Graph User",
        }
    )
    token, _ = create_session_token(user)
    ingredient = SimpleNamespace(original_text="Oats", normalized_text="oats")
    scan = SimpleNamespace(
        contract_version="3.0.0",
        ingredients=SimpleNamespace(),
        nutrition=SimpleNamespace(),
        product_name_candidates=[SimpleNamespace(value="Oat cup")],
    )
    intelligence = SimpleNamespace(
        ingredient_matches=[
            SimpleNamespace(
                ingredient=ingredient,
                taxonomy=SimpleNamespace(
                    matched=True,
                    taxonomy_id="en:oats",
                    canonical_name="Oats",
                    match_method="EXACT",
                    source_dataset="Open Food Facts",
                    source_version="test",
                ),
            )
        ],
        additives=[],
        allergens=[],
        nutrition=SimpleNamespace(
            rows=[SimpleNamespace(label="Calcium", values=["120"], units=["mg"])],
            basis="PER_SERVING",
            state="EXTRACTED",
        ),
    )
    monkeypatch.setattr(knowledge_api, "get_owned_scan_result", lambda scan_id, owner: scan)
    monkeypatch.setattr(
        knowledge_api,
        "get_r4_service",
        lambda: SimpleNamespace(analyze=lambda ingredients, nutrition: intelligence),
    )

    response = TestClient(app).get(
        "/api/v1/knowledge/scans/scan-graph/graph",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["method"] == "OBSERVED_SCAN_KNOWLEDGE_GRAPH_V1"
    assert {node["kind"] for node in payload["nodes"]} == {
        "PRODUCT",
        "INGREDIENT",
        "NUTRIENT",
    }
    assert {edge["relation"] for edge in payload["edges"]} == {
        "CONTAINS_INGREDIENT",
        "HAS_LABEL_NUTRIENT",
    }
    assert "do not establish causal health effects" in payload["limitation"]


def test_scan_graph_requires_authentication() -> None:
    assert TestClient(app).get("/api/v1/knowledge/scans/private/graph").status_code == 401


def test_health_effect_reference_is_primary_sourced_and_non_diagnostic() -> None:
    response = TestClient(app).get("/api/v1/knowledge/effects", params={"q": "calcium"})
    assert response.status_code == 200
    record = response.json()["matches"][0]
    assert record["evidence_state"] == "REFERENCE_ROLE"
    assert record["authority"] == "NIH Office of Dietary Supplements"
    assert record["dataset_version"] == "0.1.0"
    assert "not a diagnosis" in record["caution"]


def test_health_effect_reference_does_not_invent_unknown_matches() -> None:
    response = TestClient(app).get(
        "/api/v1/knowledge/effects", params={"q": "miracle detox nutrient"}
    )
    assert response.status_code == 200
    assert response.json()["matches"] == []


def test_alternative_ingredient_mapping_is_versioned_and_non_equivalent() -> None:
    response = TestClient(app).get("/api/v1/knowledge/substitutions", params={"q": "white beans"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["method"] == "CURATED_FUNCTIONAL_SUBSTITUTION_LEXICAL_RETRIEVAL_V1"
    mapping = payload["matches"][0]["mapping"]
    assert mapping["ingredient"] == "chickpea"
    assert mapping["alternatives"] == ["white beans"]
    assert mapping["function"] == "cooked legume base"
    assert mapping["source_version"] == "0.2.0"
    assert "not nutritionally equivalent" in payload["limitation"]

    unknown = TestClient(app).get("/api/v1/knowledge/substitutions", params={"q": "quuxylophone"})
    assert unknown.status_code == 200
    assert unknown.json()["matches"] == []
