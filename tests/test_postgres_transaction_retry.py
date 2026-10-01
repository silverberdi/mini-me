"""PostgreSQL adversarial tests for transaction retry wrapper (T13, T14)."""

import pytest

from minime.db.retry import TransactionRetryWrapper


class SyntheticPGError(Exception):
    def __init__(self, message: str, pgcode: str):
        super().__init__(message)
        self.pgcode = pgcode


def test_t13_retriable_sqlstate_recovery():
    """T13: Prove TransactionRetryWrapper retries 40001, 40P01, and conditional 55P03 up to 3 total attempts."""
    wrapper = TransactionRetryWrapper(max_attempts=3, backoff_base=0.01)

    # Verify mandatory rollback requirement
    with pytest.raises(ValueError, match="rollback_fn is required"):
        wrapper.execute(lambda: None)

    attempt_count = 0

    def retriable_op_40001():
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 3:
            raise SyntheticPGError("could not serialize access", "40001")
        return "admitted_40001"

    res1 = wrapper.execute(retriable_op_40001, rollback_fn=lambda: None)
    assert res1 == "admitted_40001"
    assert attempt_count == 3

    attempt_count_lock = 0

    def retriable_op_40p01():
        nonlocal attempt_count_lock
        attempt_count_lock += 1
        if attempt_count_lock == 1:
            raise SyntheticPGError("deadlock detected", "40P01")
        return "admitted_40P01"

    res2 = wrapper.execute(retriable_op_40p01, rollback_fn=lambda: None)
    assert res2 == "admitted_40P01"
    assert attempt_count_lock == 2

    attempt_count_lock_timeout = 0

    def retriable_op_55p03():
        nonlocal attempt_count_lock_timeout
        attempt_count_lock_timeout += 1
        if attempt_count_lock_timeout == 1:
            raise SyntheticPGError("lock_not_available", "55P03")
        return "admitted_55P03"

    res3 = wrapper.execute(retriable_op_55p03, rollback_fn=lambda: None, is_coordination_path=True)
    assert res3 == "admitted_55P03"
    assert attempt_count_lock_timeout == 2


def test_t14_non_retryable_fast_failure():
    """T14: Prove TransactionRetryWrapper immediately fails fast on 57014 and non-retryable business refusals."""
    wrapper = TransactionRetryWrapper(max_attempts=3, backoff_base=0.01)

    attempts = 0

    def query_canceled_op():
        nonlocal attempts
        attempts += 1
        raise SyntheticPGError("canceling statement due to statement timeout", "57014")

    with pytest.raises(SyntheticPGError) as excinfo:
        wrapper.execute(query_canceled_op, rollback_fn=lambda: None)

    assert excinfo.value.pgcode == "57014"
    assert attempts == 1, "57014 query_canceled must NOT be retried."

    business_attempts = 0

    def business_denial_op():
        nonlocal business_attempts
        business_attempts += 1
        raise ValueError("BUSINESS_DENIAL: budget exceeded")

    with pytest.raises(ValueError) as excinfo2:
        wrapper.execute(business_denial_op, rollback_fn=lambda: None)

    assert "BUSINESS_DENIAL" in str(excinfo2.value)
    assert business_attempts == 1, "Business denial must NOT be retried."
