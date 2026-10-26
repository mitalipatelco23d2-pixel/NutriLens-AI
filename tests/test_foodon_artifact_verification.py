"""Artifact-only CI must be explicit and must fail on altered bytes/source."""

from pathlib import Path

import pytest

from scripts.build_foodon_runtime_links import verify_runtime_artifact

ARTIFACT = Path("data/runtime/foodon-links-v0.1.0.json.gz")
R4 = Path("data/runtime/r4-taxonomies-v0.1.0.json.gz")


def test_pinned_artifact_verification_states_its_limited_scope():
    result = verify_runtime_artifact(ARTIFACT, R4)
    assert result["status"] == "PASS"
    assert result["raw_foodon_rebuilt"] is False
    assert result["validation_scope"] == "PINNED_ARTIFACT_AND_TRACKED_R4_SOURCE_ONLY"
    assert result["linked_ingredients"] > 0


def test_changed_artifact_fails_closed(tmp_path):
    altered = tmp_path / "altered.json.gz"
    altered.write_bytes(ARTIFACT.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_runtime_artifact(altered, R4)


def test_different_r4_source_fails_closed(tmp_path):
    altered = tmp_path / "different-r4.json.gz"
    altered.write_bytes(b"not-the-reviewed-taxonomy")
    with pytest.raises(ValueError, match="different R4"):
        verify_runtime_artifact(ARTIFACT, altered)
