"""Unit tests for Stage F concurrency primitives: advisory keys, savepoint recovery, and retry wrappers."""

from __future__ import annotations

import pytest

from minime.db.concurrency import (
    GLOBAL_ADMISSION_NAMESPACE,
    derive_advisory_lock_key,
    derive_global_admission_lock_key,
    derive_project_admission_lock_key,
)
from minime.db.retry import (
    execute_with_transaction_retry,
    is_retriable_sqlstate,
)


def test_advisory_lock_key_determinism():
    """Verify SHA-256 advisory lock keys are process-independent and return signed 64-bit ints."""
    key1 = derive_global_admission_lock_key()
    key2 = derive_advisory_lock_key(GLOBAL_ADMISSION_NAMESPACE)
    assert key1 == key2
    assert -9223372036854775808 <= key1 <= 9223372036854775807

    proj_key1 = derive_project_admission_lock_key("proj-alpha")
    proj_key2 = derive_project_admission_lock_key("proj-alpha")
    proj_key3 = derive_project_admission_lock_key("proj-beta")
    assert proj_key1 == proj_key2
    assert proj_key1 != proj_key3
    assert -9223372036854775808 <= proj_key1 <= 9223372036854775807


def test_retriable_sqlstate_classification():
    """Verify 40001, 40P01, conditional 55P03, and non-retryable 57014 rules."""
    err_40001 = Exception("psycopg.errors.SerializationFailure: 40001 could not serialize access")
    err_40p01 = Exception("psycopg.errors.DeadlockDetected: 40P01 deadlock detected")
    err_55p03 = Exception("psycopg.errors.LockNotAvailable: 55P03 could not obtain lock")
    err_57014 = Exception("psycopg.errors.QueryCanceled: 57014 query canceled")

    assert is_retriable_sqlstate(err_40001, is_stage_f_coordination=False) is True
    assert is_retriable_sqlstate(err_40p01, is_stage_f_coordination=False) is True

    # 55P03 is retryable ONLY when originating from Stage F lock-acquisition path
    assert is_retriable_sqlstate(err_55p03, is_stage_f_coordination=False) is False
    assert is_retriable_sqlstate(err_55p03, is_stage_f_coordination=True) is True

    # 57014 query canceled is strictly NOT retryable
    assert is_retriable_sqlstate(err_57014, is_stage_f_coordination=True) is False


def test_transaction_retry_wrapper_max_attempts():
    """Verify execute_with_transaction_retry obeys max 3 total attempts."""
    attempts = 0
    rollbacks = 0

    def mock_command():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise Exception("40001 serialization_failure")
        return "SUCCESS"

    def mock_rollback():
        nonlocal rollbacks
        rollbacks += 1

    result = execute_with_transaction_retry(
        command_fn=mock_command,
        rollback_fn=mock_rollback,
        max_attempts=3,
        is_stage_f_coordination=False,
    )
    assert result == "SUCCESS"
    assert attempts == 3
    assert rollbacks == 2


def test_transaction_retry_wrapper_exhaustion():
    """Verify retry wrapper raises exception when max attempts are exhausted."""
    attempts = 0

    def mock_failing_command():
        nonlocal attempts
        attempts += 1
        raise Exception("40001 serialization_failure")

    with pytest.raises(Exception, match="40001"):
        execute_with_transaction_retry(
            command_fn=mock_failing_command,
            rollback_fn=lambda: None,
            max_attempts=3,
        )
    assert attempts == 3
