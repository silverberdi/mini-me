"""Spend evidence remains observable and never acts as a fallback cap."""
from decimal import Decimal

from minime.domain.models import BudgetLedgerEntry
from minime.services.agent_runner import CliAgentRunner
from minime.services.budget_service import BudgetService


def test_openrouter_preflight_does_not_read_legacy_budget_policy():
    runner = CliAgentRunner()
    runner.check_capacity_preflight("mini-me", "openrouter", "implementer")


def test_provider_usage_breakdown_uses_only_persisted_ledger_facts(in_memory_uow):
    in_memory_uow.budget_ledger.save(
        BudgetLedgerEntry(
            project_id="mini-me",
            job_id="job-1",
            change_id="change-1",
            provider="openrouter",
            billing_origin="openrouter",
            role="implementer",
            canonical_model_identity="deepseek/deepseek-chat",
            prompt_tokens=40,
            completion_tokens=15,
            total_tokens=55,
            amount_usd=Decimal("0.125"),
            entry_type="USAGE",
        )
    )
    breakdown = BudgetService(in_memory_uow).get_token_usage_breakdown("mini-me")
    assert breakdown["deepseek/deepseek-chat"] == {
        "prompt_tokens": 40,
        "completion_tokens": 15,
        "total_tokens": 55,
        "amount_usd": Decimal("0.125"),
        "call_count": 1,
    }
