"""Pattern A Savepoint Conflict Normalization primitives for Stage F database concurrency control."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

T = TypeVar("T")


def is_expected_constraint_violation(exc: IntegrityError, constraint_name: str) -> bool:
    """Check if an IntegrityError matches the expected named constraint or index."""
    err_str = str(exc.orig) if hasattr(exc, "orig") and exc.orig else str(exc)
    if constraint_name in err_str:
        return True
    if hasattr(exc, "args") and any(constraint_name in str(a) for a in exc.args):
        return True
    return False


def execute_with_savepoint_recovery(
    session: Session,
    save_fn: Callable[[], None],
    constraint_name: str,
    recovery_fn: Callable[[], T],
) -> tuple[bool, T | None]:
    """Execute save operation inside a nested savepoint with Pattern A recovery.

    Returns:
        tuple[bool, T | None]: (True, None) if save_fn succeeded cleanly;
                              (False, recovery_result) if expected constraint collision was normalized.

    Guarantees:
    1. session.begin_nested() creates active SAVEPOINT.
    2. save_fn() inserts/updates entity.
    3. session.flush() forces constraint check INSIDE savepoint.
    4. On expected named constraint IntegrityError, savepoint rolls back cleanly.
    5. Outer transaction remains clean and usable.
    6. recovery_fn() re-reads canonical winner and returns normalized domain result.
    7. Unexpected IntegrityError is re-raised.
    """
    try:
        with session.begin_nested():
            save_fn()
            session.flush()
        return True, None
    except IntegrityError as exc:
        if not is_expected_constraint_violation(exc, constraint_name):
            raise
        # Savepoint was rolled back on block exit; outer transaction remains usable.
        return False, recovery_fn()
