"""Deterministic selection of durable intake publication ownership."""

from __future__ import annotations

from minime.domain.enums import (
    IntakeWorkspaceCreationState,
    IntakeWorkspacePublicationState,
)
from minime.domain.models import IntakeWorkspaceOwnership


class IntakeWorkspaceOwnershipSelectionError(RuntimeError):
    """Raised when durable ownership cannot identify one safe publication authority."""


def resolve_published_intake_ownership(
    ownership_repository,
    *,
    project_id: str,
    change_name: str,
    item_key: str | None = None,
    allow_released: bool = True,
) -> IntakeWorkspaceOwnership | None:
    """Resolve one published owner without allowing historical failures to shadow it.

    A currently active owner is authoritative and must itself be fully ACTIVE and
    PUBLISHED. In its absence, a single released published record may serve legacy
    handoff/readiness paths when allowed. Failed/unpublished history is never an
    authority, and contradictory or multiply-active records fail closed.
    """
    records = ownership_repository.list_by_project(project_id)
    matching = [
        record
        for record in records
        if record.change_name == change_name
        or (item_key is not None and record.item_key == item_key)
    ]
    if not matching:
        return None

    canonical_item_keys = {record.item_key for record in matching}
    if len(canonical_item_keys) != 1 or any(
        record.project_id != project_id or record.change_name != change_name for record in matching
    ):
        raise IntakeWorkspaceOwnershipSelectionError(
            "Intake ownership records contain conflicting project, item, or change identity."
        )
    if item_key is not None and next(iter(canonical_item_keys)) != item_key:
        raise IntakeWorkspaceOwnershipSelectionError(
            "Intake ownership item key does not match the requested work item."
        )

    active = [record for record in matching if record.is_active]
    if len(active) > 1:
        raise IntakeWorkspaceOwnershipSelectionError(
            "Multiple active intake workspace ownership records are ambiguous."
        )
    if active:
        owner = active[0]
        if (
            owner.creation_state != IntakeWorkspaceCreationState.ACTIVE
            or owner.publication_state != IntakeWorkspacePublicationState.PUBLISHED
        ):
            raise IntakeWorkspaceOwnershipSelectionError(
                "Active intake workspace ownership is not an active published authority."
            )
        return owner

    if not allow_released:
        raise IntakeWorkspaceOwnershipSelectionError(
            "Published intake ownership is not active for the requested operation."
        )
    released_states = {
        IntakeWorkspaceCreationState.RELEASED_PENDING_CLEANUP,
        IntakeWorkspaceCreationState.RELEASED_CLEANED,
    }
    published_history = [
        record
        for record in matching
        if record.creation_state in released_states
        and record.publication_state == IntakeWorkspacePublicationState.PUBLISHED
    ]
    if len(published_history) != 1:
        raise IntakeWorkspaceOwnershipSelectionError(
            "Historical intake ownership is missing a unique released published authority."
        )
    return published_history[0]
