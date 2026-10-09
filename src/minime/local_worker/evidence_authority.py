"""Source-backed routing evidence authority for the local worker.

Constructs trusted LocalRoutingEvidence strictly from verified canonical sources.
Callers cannot fabricate evidence booleans or supply unverified provenance.
"""

from __future__ import annotations

import logging
from typing import Any

from minime.local_worker.models import (
    LocalEvidenceAuthorityResult,
    LocalMechanicalOperation,
    LocalMutationMode,
    LocalRoutingEvidence,
    LocalRoutingEvidenceProvenance,
    LocalRoutingReasonCode,
    OperatorMechanicalCommand,
)

logger = logging.getLogger(__name__)

_SENSITIVE_READ_PATH_MARKERS = (
    "secret",
    "credential",
    ".env",
    "auth",
    "security",
    "pem",
    "key",
    "pki",
    "token",
)


class LocalRoutingEvidenceAuthority:
    """Canonical authority converting typed routing sources into trusted LocalRoutingEvidence."""

    @classmethod
    def construct_evidence(cls, source: Any | None) -> LocalEvidenceAuthorityResult:
        """Construct trusted evidence from a source object.

        V1 supports OperatorMechanicalCommand ONLY.
        Missing, untrusted, or deferred sources fail closed.
        """
        if source is None:
            return LocalEvidenceAuthorityResult(
                success=False,
                reason="Missing routing source",
                reason_code=LocalRoutingReasonCode.MISSING_ROUTING_SOURCE,
            )

        if not isinstance(source, OperatorMechanicalCommand):
            return LocalEvidenceAuthorityResult(
                success=False,
                reason=f"Unsupported routing source type '{type(source).__name__}'",
                reason_code=LocalRoutingReasonCode.UNSUPPORTED_EVIDENCE_SOURCE,
            )

        cmd: OperatorMechanicalCommand = source

        authoritative_supplied = cmd.authoritative_change is not None
        deterministic_supplied = cmd.deterministic_acceptance is not None

        if cmd.mutation_mode == LocalMutationMode.MUTATING:
            if not cmd.target_file or not isinstance(cmd.target_file, str) or not cmd.target_file.strip():
                return LocalEvidenceAuthorityResult(
                    success=False,
                    reason="Mutating command missing or empty target file",
                    reason_code=LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED,
                )
            target = cmd.target_file.strip()
            if target.startswith("/") or target.startswith("\\"):
                return LocalEvidenceAuthorityResult(
                    success=False,
                    reason="Mutating command target file is an absolute path",
                    reason_code=LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED,
                )
            if ".." in target.split("/") or ".." in target.split("\\"):
                return LocalEvidenceAuthorityResult(
                    success=False,
                    reason="Mutating command target file contains directory traversal",
                    reason_code=LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED,
                )
            if "*" in target or "?" in target:
                return LocalEvidenceAuthorityResult(
                    success=False,
                    reason="Mutating command target file contains forbidden wildcards",
                    reason_code=LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED,
                )
            if target.endswith("/") or target.endswith("\\"):
                return LocalEvidenceAuthorityResult(
                    success=False,
                    reason="Mutating command target file appears to be a directory",
                    reason_code=LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED,
                )
            if not authoritative_supplied:
                return LocalEvidenceAuthorityResult(
                    success=False,
                    reason="Mutating command missing authoritative change payload",
                    reason_code=LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED,
                )
            if not deterministic_supplied:
                return LocalEvidenceAuthorityResult(
                    success=False,
                    reason="Mutating command missing deterministic acceptance payload",
                    reason_code=LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED,
                )
            if cmd.requires_discovery:
                return LocalEvidenceAuthorityResult(
                    success=False,
                    reason="Mutating command flagged with requires_discovery=True",
                    reason_code=LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED,
                )
            if cmd.unresolved_ambiguity:
                return LocalEvidenceAuthorityResult(
                    success=False,
                    reason="Mutating command flagged with unresolved_ambiguity=True",
                    reason_code=LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED,
                )
        elif cmd.mutation_mode == LocalMutationMode.READ_ONLY:
            if cmd.operation_type != LocalMechanicalOperation.LOG_DIAGNOSTIC:
                return LocalEvidenceAuthorityResult(
                    success=False,
                    reason=f"Read-only operation type '{cmd.operation_type.value}' not supported",
                    reason_code=LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED,
                )
            if not cmd.read_sources or not isinstance(cmd.read_sources, list):
                return LocalEvidenceAuthorityResult(
                    success=False,
                    reason="Read-only command missing explicit bounded read sources",
                    reason_code=LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED,
                )
            for path in cmd.read_sources:
                if not isinstance(path, str) or not path.strip():
                    return LocalEvidenceAuthorityResult(
                        success=False,
                        reason="Read-only read source path must be a non-empty string",
                        reason_code=LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED,
                    )
                if "*" in path or "?" in path:
                    return LocalEvidenceAuthorityResult(
                        success=False,
                        reason=f"Read source path '{path}' contains forbidden wildcards",
                        reason_code=LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED,
                    )
                if ".." in path:
                    return LocalEvidenceAuthorityResult(
                        success=False,
                        reason=f"Read source path '{path}' contains directory traversal",
                        reason_code=LocalRoutingReasonCode.AUTHORITY_CONSTRUCTION_FAILED,
                    )
                lowered = path.lower()
                if any(marker in lowered for marker in _SENSITIVE_READ_PATH_MARKERS):
                    return LocalEvidenceAuthorityResult(
                        success=False,
                        reason=f"Read source path '{path}' touches sensitive auth/secret keyword",
                        reason_code=LocalRoutingReasonCode.FORBIDDEN_SURFACE,
                    )

        evidence = LocalRoutingEvidence(
            operation_type=cmd.operation_type,
            mutation_mode=cmd.mutation_mode,
            target_file=cmd.target_file,
            target_symbol=cmd.target_symbol,
            authoritative_change_supplied=authoritative_supplied,
            deterministic_acceptance_supplied=deterministic_supplied,
            requires_discovery=cmd.requires_discovery,
            unresolved_ambiguity=cmd.unresolved_ambiguity,
            read_sources=list(cmd.read_sources),
            provenance=LocalRoutingEvidenceProvenance.OPERATOR_EXPLICIT_MECHANICAL_COMMAND,
        )

        return LocalEvidenceAuthorityResult(
            success=True,
            evidence=evidence,
            reason="Trusted evidence constructed successfully",
            reason_code=LocalRoutingReasonCode.LOCAL_ELIGIBLE_EXPLICIT_LOW_COMPLEXITY,
        )
