"""Canonical Lifecycle Transition Authority for mini me."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from minime.db.models import BacklogItemModel, ChangeModel
from minime.domain.enums import ChangeStatus, EventType, WorkItemStatus
from minime.domain.exceptions import (
    LifecycleInvalidTransitionError,
    LifecycleTransitionConflictError,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import BacklogItem, Change, Event, utc_now

logger = logging.getLogger(__name__)

# Canonical ChangeStatus transition matrix
ALLOWED_CHANGE_TRANSITIONS: dict[ChangeStatus, set[ChangeStatus]] = {
    ChangeStatus.DISCOVERED: {ChangeStatus.READY, ChangeStatus.BLOCKED, ChangeStatus.CANCELLED},
    ChangeStatus.READY: {ChangeStatus.IN_PROGRESS, ChangeStatus.BLOCKED, ChangeStatus.CANCELLED},
    ChangeStatus.IN_PROGRESS: {ChangeStatus.BLOCKED, ChangeStatus.DONE, ChangeStatus.CANCELLED},
    ChangeStatus.BLOCKED: {ChangeStatus.READY, ChangeStatus.IN_PROGRESS, ChangeStatus.CANCELLED},
    ChangeStatus.DONE: set(),
    ChangeStatus.CANCELLED: set(),
}

# Canonical WorkItemStatus transition matrix
ALLOWED_WORK_ITEM_TRANSITIONS: dict[WorkItemStatus, set[WorkItemStatus]] = {
    WorkItemStatus.BACKLOG: {WorkItemStatus.CONTEXT_CHECK, WorkItemStatus.PREPARING, WorkItemStatus.CANCELLED},
    WorkItemStatus.CONTEXT_CHECK: {WorkItemStatus.PREPARING, WorkItemStatus.NEEDS_HUMAN, WorkItemStatus.BLOCKED, WorkItemStatus.CANCELLED},
    WorkItemStatus.PREPARING: {WorkItemStatus.NEEDS_HUMAN, WorkItemStatus.READY, WorkItemStatus.BLOCKED, WorkItemStatus.CANCELLED},
    WorkItemStatus.NEEDS_HUMAN: {WorkItemStatus.PREPARING, WorkItemStatus.BLOCKED, WorkItemStatus.CANCELLED},
    WorkItemStatus.READY: {WorkItemStatus.ADMITTED, WorkItemStatus.NEEDS_HUMAN, WorkItemStatus.BLOCKED, WorkItemStatus.CANCELLED},
    WorkItemStatus.ADMITTED: {WorkItemStatus.RUNNING, WorkItemStatus.NEEDS_HUMAN, WorkItemStatus.BLOCKED, WorkItemStatus.CANCELLED},
    WorkItemStatus.RUNNING: {WorkItemStatus.NEEDS_HUMAN, WorkItemStatus.BLOCKED, WorkItemStatus.COMPLETED, WorkItemStatus.CANCELLED},
    WorkItemStatus.BLOCKED: {WorkItemStatus.PREPARING, WorkItemStatus.READY, WorkItemStatus.NEEDS_HUMAN, WorkItemStatus.CANCELLED},
    WorkItemStatus.COMPLETED: set(),
    WorkItemStatus.CANCELLED: set(),
}


class LifecycleTransitionAuthority:
    """Single canonical authority for durable Change and BacklogItem lifecycle transitions."""

    def __init__(self, uow: PersistenceUnitOfWork):
        self.uow = uow

    @property
    def session(self) -> Session | None:
        if hasattr(self.uow, "session") and getattr(self.uow, "session") is not None:
            return getattr(self.uow, "session")
        if hasattr(self.uow, "_session") and getattr(self.uow, "_session") is not None:
            return getattr(self.uow, "_session")
        return None

    def transition_change(
        self,
        project_id: str,
        name: str,
        expected_from_state: ChangeStatus,
        to_state: ChangeStatus,
        stage: str | None = None,
        reason_code: str = "state_transition",
        actor: str = "authority",
        correlation_id: str | None = None,
        evidence_references: dict[str, Any] | None = None,
    ) -> Change:
        """Execute an atomic CAS status transition for Change."""
        allowed_targets = ALLOWED_CHANGE_TRANSITIONS.get(expected_from_state, set())
        if to_state not in allowed_targets:
            raise LifecycleInvalidTransitionError(
                f"Invalid Change transition: '{expected_from_state.value}' -> '{to_state.value}' is not allowed."
            )

        change = self.uow.changes.get_by_name(project_id, name)
        if not change:
            raise LifecycleTransitionConflictError(f"Change '{name}' for project '{project_id}' not found.")

        if change.status != expected_from_state:
            raise LifecycleTransitionConflictError(
                f"Stale state conflict: Change '{name}' is in state '{change.status.value}', expected '{expected_from_state.value}'."
            )

        now = utc_now()
        session = self.session
        try:
            if session is not None and hasattr(session, "execute"):
                stmt = (
                    update(ChangeModel)
                    .where(
                        ChangeModel.id == change.change_id,
                        ChangeModel.status == expected_from_state.value,
                    )
                    .values(
                        status=to_state.value,
                        stage=stage if stage is not None else ChangeModel.stage,
                        updated_at=now,
                    )
                )
                res = session.execute(stmt)
                if res.rowcount == 0:
                    raise LifecycleTransitionConflictError(
                        f"Atomic CAS failed for Change '{name}': expected status '{expected_from_state.value}' conflict."
                    )
                if hasattr(session, "flush"):
                    session.flush()
            elif hasattr(self.uow.changes, "_store"):
                stored = self.uow.changes._store.get(change.change_id)
                if not stored or stored.status != expected_from_state:
                    raise LifecycleTransitionConflictError(
                        f"Atomic CAS failed for Change '{name}': expected status '{expected_from_state.value}' conflict."
                    )
                updated = stored.model_copy(deep=True)
                updated.status = to_state
                if stage is not None:
                    updated.stage = stage
                updated.updated_at = now
                self.uow.changes._store[change.change_id] = updated
            else:
                raise NotImplementedError("Unsupported UoW/Repository implementation for LifecycleTransitionAuthority")

            # Atomic Event emission in same DB transaction
            event = Event(
                event_type=EventType.LIFECYCLE_TRANSITION,
                project_id=project_id,
                change_id=name,
                payload={
                    "aggregate_type": "Change",
                    "aggregate_id": change.change_id,
                    "project_id": project_id,
                    "change_name": name,
                    "from_state": expected_from_state.value,
                    "to_state": to_state.value,
                    "reason_code": reason_code,
                    "actor": actor,
                    "correlation_id": correlation_id,
                    "evidence_references": evidence_references or {},
                },
                timestamp=now,
            )
            self.uow.events.save(event)
        except Exception:
            if session is not None and hasattr(session, "rollback"):
                session.rollback()
            raise

        updated_change = self.uow.changes.get_by_name(project_id, name)
        return updated_change or change

    def transition_backlog_item(
        self,
        project_id: str,
        item_key: str,
        expected_from_state: WorkItemStatus,
        to_state: WorkItemStatus,
        run_id: str | None = None,
        reason_code: str = "state_transition",
        actor: str = "authority",
        correlation_id: str | None = None,
        evidence_references: dict[str, Any] | None = None,
    ) -> BacklogItem:
        """Execute an atomic CAS status transition for BacklogItem."""
        allowed_targets = ALLOWED_WORK_ITEM_TRANSITIONS.get(expected_from_state, set())
        if to_state not in allowed_targets:
            raise LifecycleInvalidTransitionError(
                f"Invalid WorkItem transition: '{expected_from_state.value}' -> '{to_state.value}' is not allowed."
            )

        item = self.uow.backlog_items.get_by_project_and_key(project_id, item_key)
        if not item:
            raise LifecycleTransitionConflictError(f"BacklogItem '{item_key}' for project '{project_id}' not found.")

        if item.status != expected_from_state:
            raise LifecycleTransitionConflictError(
                f"Stale state conflict: BacklogItem '{item_key}' is in state '{item.status.value}', expected '{expected_from_state.value}'."
            )

        now = utc_now()
        session = self.session
        try:
            if session is not None and hasattr(session, "execute"):
                stmt = (
                    update(BacklogItemModel)
                    .where(
                        BacklogItemModel.id == item.item_id,
                        BacklogItemModel.status == expected_from_state.value,
                    )
                    .values(
                        status=to_state.value,
                        run_id=run_id if run_id is not None else BacklogItemModel.run_id,
                        updated_at=now,
                    )
                )
                res = session.execute(stmt)
                if res.rowcount == 0:
                    raise LifecycleTransitionConflictError(
                        f"Atomic CAS failed for BacklogItem '{item_key}': expected status '{expected_from_state.value}' conflict."
                    )
                if hasattr(session, "flush"):
                    session.flush()
            elif hasattr(self.uow.backlog_items, "_store"):
                stored = self.uow.backlog_items._store.get(item.item_id)
                if not stored or stored.status != expected_from_state:
                    raise LifecycleTransitionConflictError(
                        f"Atomic CAS failed for BacklogItem '{item_key}': expected status '{expected_from_state.value}' conflict."
                    )
                updated = stored.model_copy(deep=True)
                updated.status = to_state
                if run_id is not None:
                    updated.run_id = run_id
                updated.updated_at = now
                self.uow.backlog_items._store[item.item_id] = updated
            else:
                raise NotImplementedError("Unsupported UoW/Repository implementation for LifecycleTransitionAuthority")

            # Atomic Event emission in same DB transaction
            event = Event(
                event_type=EventType.LIFECYCLE_TRANSITION,
                project_id=project_id,
                change_id=item.openspec_change_name or item_key,
                payload={
                    "aggregate_type": "BacklogItem",
                    "aggregate_id": item.item_id,
                    "project_id": project_id,
                    "item_key": item_key,
                    "from_state": expected_from_state.value,
                    "to_state": to_state.value,
                    "reason_code": reason_code,
                    "actor": actor,
                    "correlation_id": correlation_id,
                    "evidence_references": evidence_references or {},
                },
                timestamp=now,
            )
            self.uow.events.save(event)
        except Exception:
            if session is not None and hasattr(session, "rollback"):
                session.rollback()
            raise

        updated_item = self.uow.backlog_items.get_by_project_and_key(project_id, item_key)
        return updated_item or item
