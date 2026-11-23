"""Focused contract tests for verified, durable provider cost settlement."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from minime.services.budget_service import ObservedCost, ObservedCostSettlementService


class Ledger:
    def __init__(self):
        self.entries = []

    def get_by_usage_identity(self, identity):
        return next((entry for entry in self.entries if entry.usage_identity == identity), None)

    def save(self, entry):
        self.entries.append(entry)


class Uow:
    def __init__(self):
        self.budget_ledger = Ledger()


def observed(**overrides):
    values = dict(
        project_id="project-1",
        job_id="job-1",
        change_id="change-1",
        provider="OpenRouter",
        model="openrouter/deepseek/deepseek-r1",
        amount_usd=Decimal("0.120001"),
        usage_identity="provider-invocation-1",
        observed_at=datetime(2026, 11, 23, 12, 0, tzinfo=UTC),
        source="openrouter-response",
    )
    values.update(overrides)
    return ObservedCost(**values)


@pytest.mark.parametrize(
    "change",
    [
        {"amount_usd": None},
        {"observed_at": datetime(2026, 11, 23, 12, 0)},
        {"provider": "unknown-provider"},
        {"amount_usd": Decimal("0")},
    ],
)
def test_settlement_rejects_incomplete_or_synthetic_evidence(change):
    with pytest.raises(ValueError):
        ObservedCostSettlementService(Uow()).settle(observed(**change))


def test_settlement_is_idempotent_and_preserves_precision():
    uow = Uow()
    service = ObservedCostSettlementService(uow)
    first = service.settle(observed())
    second = service.settle(observed())

    assert second.entry_id == first.entry_id
    assert len(uow.budget_ledger.entries) == 1
    assert first.amount_usd == Decimal("0.120001")
    assert first.observed_at == datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("provider", ["codex", "deepseek", "openrouter"])
def test_settlement_accepts_only_explicitly_admitted_provider_names(provider):
    entry = ObservedCostSettlementService(Uow()).settle(observed(provider=provider))

    assert entry.provider == provider
