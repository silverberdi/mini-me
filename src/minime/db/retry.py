"""Transaction retry policy primitives for Stage F concurrency control."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.exc import DBAPIError

T = TypeVar("T")
logger = logging.getLogger(__name__)


class NonRetryableTransactionError(Exception):
    """Exception indicating a transaction error that must not be automatically retried."""


def is_retriable_sqlstate(exc: Exception, is_stage_f_coordination: bool = False) -> bool:
    """Classify whether a database exception is retryable under Stage F policy.

    Always retryable (when command body is retry-safe):
    - 40001 (serialization_failure)
    - 40P01 (deadlock_detected)

    Conditionally retryable:
    - 55P03 (lock_not_available) ONLY when is_stage_f_coordination is True.

    Explicitly NOT retryable:
    - 57014 (query_canceled)
    - 23505 (unique_violation)
    - Non-DB business/policy errors
    """
    sqlstate: str | None = None

    if isinstance(exc, DBAPIError) and hasattr(exc, "orig") and exc.orig:
        sqlstate = getattr(exc.orig, "pgcode", None) or getattr(exc.orig, "sqlstate", None)

    if not sqlstate and hasattr(exc, "pgcode"):
        sqlstate = getattr(exc, "pgcode")

    if not sqlstate:
        # Check string representation for SQLSTATE indicators
        err_str = str(exc)
        if "40001" in err_str or "serialization_failure" in err_str or "could not serialize" in err_str:
            sqlstate = "40001"
        elif "40P01" in err_str or "deadlock_detected" in err_str or "deadlock detected" in err_str:
            sqlstate = "40P01"
        elif "55P03" in err_str or "lock_not_available" in err_str or "could not obtain lock" in err_str:
            sqlstate = "55P03"

    if sqlstate == "40001" or sqlstate == "40P01":
        return True

    if sqlstate == "55P03" and is_stage_f_coordination:
        return True

    return False


def execute_with_transaction_retry(
    command_fn: Callable[[], T],
    rollback_fn: Callable[[], None],
    max_attempts: int = 3,
    is_stage_f_coordination: bool = False,
    command_identity: str | None = None,
) -> T:
    """Execute a transactional command with bounded retry policy.

    Max attempts: 3 total (Attempt 1 initial + at most 2 retries).
    Each retry:
    1. Executing rollback_fn() to clean transaction state.
    2. Exponential backoff with random jitter.
    3. Re-executing command_fn() which re-establishes clean transaction, re-acquires locks, and re-reads state.
    """
    attempt = 1
    while True:
        try:
            return command_fn()
        except Exception as exc:
            if attempt >= max_attempts or not is_retriable_sqlstate(exc, is_stage_f_coordination=is_stage_f_coordination):
                raise

            logger.warning(
                "Transient DB concurrency failure on attempt %d/%d for '%s': %s. Retrying after rollback...",
                attempt,
                max_attempts,
                command_identity or "command",
                exc,
            )
            try:
                rollback_fn()
            except Exception as rb_exc:
                logger.warning("Rollback failed during retry prep: %s", rb_exc)

            # Exponential backoff with jitter: Attempt 1 -> 50ms ± 15ms; Attempt 2 -> 150ms ± 30ms
            base_backoff = 0.05 * (3 ** (attempt - 1))
            jitter = random.uniform(-0.3 * base_backoff, 0.3 * base_backoff)
            sleep_time = max(0.01, base_backoff + jitter)
            time.sleep(sleep_time)

            attempt += 1


class TransactionRetryWrapper:
    """Wrapper executing transactional commands with bounded retry policy."""

    def __init__(
        self,
        max_attempts: int = 3,
        backoff_base: float = 0.05,
        is_coordination_path: bool = False,
    ):
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self.is_coordination_path = is_coordination_path

    def execute(
        self,
        command_fn: Callable[[], T],
        rollback_fn: Callable[[], None] | None = None,
        is_coordination_path: bool | None = None,
        command_identity: str | None = None,
    ) -> T:
        coordination = (
            is_coordination_path
            if is_coordination_path is not None
            else self.is_coordination_path
        )
        rb = rollback_fn or (lambda: None)
        attempt = 1
        while True:
            try:
                return command_fn()
            except Exception as exc:
                if attempt >= self.max_attempts or not is_retriable_sqlstate(
                    exc, is_stage_f_coordination=coordination
                ):
                    raise
                logger.warning(
                    "Transient DB concurrency failure on attempt %d/%d for '%s': %s. Retrying...",
                    attempt,
                    self.max_attempts,
                    command_identity or "command",
                    exc,
                )
                try:
                    rb()
                except Exception as rb_exc:
                    logger.warning("Rollback failed during retry prep: %s", rb_exc)

                base_backoff = self.backoff_base * (3 ** (attempt - 1))
                jitter = random.uniform(-0.3 * base_backoff, 0.3 * base_backoff)
                sleep_time = max(0.001, base_backoff + jitter)
                time.sleep(sleep_time)
                attempt += 1

