"""Blocker claim validation service and deterministic fingerprinting."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

from minime.domain.enums import BlockerValidationVerdict
from minime.domain.models import BlockerClaimPayload

logger = logging.getLogger(__name__)


def compute_blocker_fingerprint(
    blocker_type: str,
    affected_requirement: str | None = None,
    failing_invariant: str | None = None,
    normalized_reason_code: str | None = None,
) -> str:
    """Deterministically compute SHA-256 fingerprint for a blocker claim."""
    norm_type = (blocker_type or "").strip().lower()
    norm_req = (affected_requirement or "").strip().lower()
    norm_inv = (failing_invariant or "").strip().lower()
    norm_reason = (normalized_reason_code or "").strip().lower()

    raw = f"{norm_type}|{norm_req}|{norm_inv}|{norm_reason}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class BlockerValidationContext:
    """Contextual information needed to validate an executor's blocker claim."""

    change_name: str
    openspec_requirements: list[str] = field(default_factory=list)
    available_integration_points: list[dict[str, Any]] = field(default_factory=list)
    existing_files: list[str] = field(default_factory=list)
    required_files: list[str] = field(default_factory=list)
    candidate_tree_files: list[str] = field(default_factory=list)
    manifest_files: list[str] = field(default_factory=list)
    base_diff_files: list[str] = field(default_factory=list)


@dataclass
class BlockerValidationResult:
    """Result of deterministic blocker validation."""

    verdict: BlockerValidationVerdict
    rationale: str
    is_agent_solvable: bool
    fingerprint: str
    available_integration_points: list[dict[str, Any]] = field(default_factory=list)


class BlockerValidationService:
    """Validates blocker claims without LLM speculation."""

    def compute_fingerprint(self, payload: BlockerClaimPayload) -> str:
        return compute_blocker_fingerprint(
            blocker_type=payload.blocker_type,
            affected_requirement=payload.affected_requirement,
            failing_invariant=payload.failing_invariant,
            normalized_reason_code=payload.normalized_reason_code,
        )

    def validate_missing_file(
        self, location: str | None, context: BlockerValidationContext
    ) -> BlockerValidationResult:
        """Validate a reviewer missing-file claim against frozen tree evidence."""
        claimed = (location or "").strip().lstrip("./")
        payload = BlockerClaimPayload(
            blocker_type="MISSING_FILE",
            location=claimed or None,
            rationale="Reviewer claims a required file is missing.",
            is_agent_solvable=True,
        )
        return self.validate(payload, context)

    def validate(
        self,
        payload: BlockerClaimPayload,
        context: BlockerValidationContext,
    ) -> BlockerValidationResult:
        """Deterministically validate a blocker claim."""
        fingerprint = self.compute_fingerprint(payload)
        btype = (payload.blocker_type or "").strip().upper()
        rationale = payload.rationale or ""
        failing_inv = payload.failing_invariant or ""
        req = payload.affected_requirement or ""

        # 1. False Blocker: Missing non-existent code/file/class that is an implementation target
        false_blocker_types = {
            "MISSING_FILE",
            "MISSING_MODULE",
            "MISSING_CLASS",
            "UNIMPLEMENTED_INTERFACE",
            "MISSING_TEST",
        }
        if btype in false_blocker_types or any(
            phrase in rationale.lower()
            for phrase in [
                "does not exist",
                "file not found",
                "module not found",
                "class not found",
                "needs to be implemented",
            ]
        ):
            claimed = (payload.location or "").strip().lstrip("./")
            if claimed and (context.required_files or context.candidate_tree_files or context.manifest_files):
                tree_files = {
                    str(path).strip().lstrip("./")
                    for path in (*context.candidate_tree_files, *context.manifest_files)
                }
                required_files = {
                    str(path).strip().lstrip("./") for path in context.required_files
                }
                in_tree = claimed in tree_files
                explicitly_required = claimed in required_files
                if explicitly_required and not in_tree:
                    return BlockerValidationResult(
                        verdict=BlockerValidationVerdict.REAL_BLOCKER,
                        rationale=f"Required file '{claimed}' is absent from the authoritative candidate tree at candidate SHA.",
                        is_agent_solvable=True,
                        fingerprint=fingerprint,
                        available_integration_points=context.available_integration_points,
                    )
                if in_tree or not explicitly_required:
                    return BlockerValidationResult(
                        verdict=BlockerValidationVerdict.FALSE_BLOCKER,
                        rationale=f"Missing-file claim for '{claimed}' is not a contractual absence in the frozen candidate tree.",
                        is_agent_solvable=True,
                        fingerprint=fingerprint,
                        available_integration_points=context.available_integration_points,
                    )
            # Check if this is an internal artifact to be created
            return BlockerValidationResult(
                verdict=BlockerValidationVerdict.FALSE_BLOCKER,
                rationale="Missing module, class, file, or test is an implementation responsibility of the agent under OpenSpec tasks.",
                is_agent_solvable=True,
                fingerprint=fingerprint,
                available_integration_points=context.available_integration_points,
            )

        # 2. Real Blocker: External upstream requirement contradiction or impossible invariant
        real_blocker_types = {
            "REQUIREMENT_CONTRADICTION",
            "UPSTREAM_DEPENDENCY_DEFECT",
            "UNRESOLVABLE_SCHEMA_COLLISION",
            "IMMUTABLE_CONTRACT_VIOLATION",
        }
        if btype in real_blocker_types:
            return BlockerValidationResult(
                verdict=BlockerValidationVerdict.REAL_BLOCKER,
                rationale=f"Validated external requirement contradiction or immutable contract violation: {req} / {failing_inv}",
                is_agent_solvable=False,
                fingerprint=fingerprint,
                available_integration_points=context.available_integration_points,
            )

        # 3. Scope / Architecture check: if agent solvable flag was explicitly set to True
        if payload.is_agent_solvable:
            return BlockerValidationResult(
                verdict=BlockerValidationVerdict.FALSE_BLOCKER,
                rationale="Blocker is classified as agent-solvable within workspace scope.",
                is_agent_solvable=True,
                fingerprint=fingerprint,
                available_integration_points=context.available_integration_points,
            )

        # 4. Fail-closed default: if claimed unsolvable without proven internal alternative -> Real Blocker
        return BlockerValidationResult(
            verdict=BlockerValidationVerdict.REAL_BLOCKER,
            rationale=f"Claimed unsolvable blocker: {payload.rationale or payload.blocker_type}",
            is_agent_solvable=False,
            fingerprint=fingerprint,
            available_integration_points=context.available_integration_points,
        )
