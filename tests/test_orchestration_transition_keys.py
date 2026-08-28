"""Bounded deterministic transition-key contract tests."""

from __future__ import annotations

from minime.db.models import OrchestrationStageEventModel
from minime.services.orchestration_service import (
    ORCHESTRATION_TRANSITION_KEY_MAX_LENGTH,
    bounded_orchestration_transition_key,
)


def test_record_adoption_key_is_deterministic_and_bounded():
    identity = {
        "run_id": "e7e63eb9-f372-49ce-bcc8-d979de2e70e0",
        "candidate_generation": 1,
        "base_sha": "a" * 40,
        "candidate_sha": "b" * 40,
        "manifest_hash": "c" * 64,
    }
    first = bounded_orchestration_transition_key("LCRE", identity)
    assert first == bounded_orchestration_transition_key("LCRE", dict(reversed(identity.items())))
    assert len(first) <= ORCHESTRATION_TRANSITION_KEY_MAX_LENGTH
    assert len(first) == len("LCRE:") + 64


def test_ref_adoption_and_human_resolution_keys_are_bounded_and_distinct():
    ref_identity = {
        "run_id": "e7e63eb9-f372-49ce-bcc8-d979de2e70e0",
        "candidate_generation": 1,
        "candidate_sha": "b" * 40,
        "adopted_candidate_ref": "refs/heads/minime/" + "very-long-change-name-" * 8 + "job",
    }
    resolution_identity = {
        "run_id": ref_identity["run_id"],
        "candidate_generation": 1,
        "candidate_sha": ref_identity["candidate_sha"],
        "target_base_sha": "d" * 40,
        "resolution_action": "CONTINUE_PRESERVED_CANDIDATE",
    }
    ref_key = bounded_orchestration_transition_key("LCREF", ref_identity)
    resolution_key = bounded_orchestration_transition_key("HRES", resolution_identity)
    assert len(ref_key) <= ORCHESTRATION_TRANSITION_KEY_MAX_LENGTH
    assert len(resolution_key) <= ORCHESTRATION_TRANSITION_KEY_MAX_LENGTH
    assert ref_key == bounded_orchestration_transition_key("LCREF", ref_identity)
    assert resolution_key == bounded_orchestration_transition_key("HRES", resolution_identity)
    assert ref_key != bounded_orchestration_transition_key(
        "LCREF", {**ref_identity, "candidate_sha": "e" * 40}
    )


def test_transition_key_schema_boundary_remains_128():
    assert OrchestrationStageEventModel.transition_key.property.columns[0].type.length == 128
