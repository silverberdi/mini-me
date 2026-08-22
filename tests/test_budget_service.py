"""Unit and concurrency tests for BudgetService, policy locking, and exact Decimal headroom calculation."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from minime.domain.enums import EventType
from minime.domain.models import OpenRouterBudgetPolicy, OpenRouterPricingSnapshot
from minime.services.budget_service import BudgetService


def _policy(
    project_id: str = "mini-me",
    enabled: bool = True,
    daily_cap: str = "10.00",
    monthly_cap: str = "25.00",
    is_breached: bool = False,
) -> OpenRouterBudgetPolicy:
    return OpenRouterBudgetPolicy(
        project_id=project_id,
        enabled=enabled,
        daily_cap_usd=Decimal(daily_cap),
        monthly_cap_usd=Decimal(monthly_cap),
        currency="USD",
        policy_version=1,
        is_breached=is_breached,
        updated_at=datetime(2026, 8, 21, tzinfo=UTC),
    )


def _snapshot(
    snapshot_id: str = "snap-1",
    prompt_price: str = "0.001",
    output_price: str = "0.002",
    additional: str = "0.5",
    canonical_model_identity: str = "qwen:qwen3-coder",
    routed_model_identity: str = "qwen/qwen3-coder",
    source: str = "openrouter_catalog_api",
) -> OpenRouterPricingSnapshot:
    return OpenRouterPricingSnapshot(
        snapshot_id=snapshot_id,
        canonical_model_identity=canonical_model_identity,
        routed_model_identity=routed_model_identity,
        prompt_price_per_token=Decimal(prompt_price),
        output_price_per_token=Decimal(output_price),
        additional_cost_per_request=Decimal(additional),
        currency="USD",
        source=source,
        observed_at=datetime(2026, 8, 21, tzinfo=UTC),
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
    )


def test_reserve_budget_denies_missing_policy(in_memory_uow):
    service = BudgetService(in_memory_uow)
    reservation, reason, headroom = service.reserve_budget(
        project_id="mini-me",
        job_id="job-1",
        change_id="change-1",
        role="reviewer",
        canonical_model_identity="qwen:qwen3-coder",
        pricing_snapshot=_snapshot(),
        prompt_token_upper_bound=100,
        max_output_tokens=100,
    )
    assert reservation is None
    assert reason == "policy_denied"
    assert headroom is None


def test_reserve_budget_denies_disabled_policy(in_memory_uow):
    in_memory_uow.budget_policies.save(_policy(enabled=False))
    service = BudgetService(in_memory_uow)
    reservation, reason, _ = service.reserve_budget(
        project_id="mini-me",
        job_id="job-1",
        change_id="change-1",
        role="reviewer",
        canonical_model_identity="qwen:qwen3-coder",
        pricing_snapshot=_snapshot(),
        prompt_token_upper_bound=100,
        max_output_tokens=100,
    )
    assert reservation is None
    assert reason == "policy_denied"


def test_reserve_budget_denies_zero_or_negative_caps(in_memory_uow):
    in_memory_uow.budget_policies.save(_policy(daily_cap="0.00", monthly_cap="10.00"))
    service = BudgetService(in_memory_uow)
    reservation, reason, _ = service.reserve_budget(
        project_id="mini-me",
        job_id="job-1",
        change_id="change-1",
        role="reviewer",
        canonical_model_identity="qwen:qwen3-coder",
        pricing_snapshot=_snapshot(),
        prompt_token_upper_bound=100,
        max_output_tokens=100,
    )
    assert reservation is None
    assert reason == "policy_denied"


def test_reserve_budget_denies_breached_policy(in_memory_uow):
    in_memory_uow.budget_policies.save(_policy(is_breached=True))
    service = BudgetService(in_memory_uow)
    reservation, reason, _ = service.reserve_budget(
        project_id="mini-me",
        job_id="job-1",
        change_id="change-1",
        role="reviewer",
        canonical_model_identity="qwen:qwen3-coder",
        pricing_snapshot=_snapshot(),
        prompt_token_upper_bound=100,
        max_output_tokens=100,
    )
    assert reservation is None
    assert reason == "policy_denied"


def test_reserve_budget_denies_missing_or_invalid_tokens(in_memory_uow):
    in_memory_uow.budget_policies.save(_policy())
    service = BudgetService(in_memory_uow)
    reservation, reason, _ = service.reserve_budget(
        project_id="mini-me",
        job_id="job-1",
        change_id="change-1",
        role="reviewer",
        canonical_model_identity="qwen:qwen3-coder",
        pricing_snapshot=_snapshot(),
        prompt_token_upper_bound=100,
        max_output_tokens=0,
    )
    assert reservation is None
    assert reason == "policy_denied"


def test_sync_policy_preserves_breached_state(in_memory_uow):
    in_memory_uow.budget_policies.save(_policy(is_breached=True))
    service = BudgetService(in_memory_uow)
    # Re-syncing with is_breached=False in config must NOT clear the breach
    updated = service.sync_policy_from_config(
        project_id="mini-me",
        enabled=True,
        daily_cap_usd="20.00",
        monthly_cap_usd="50.00",
        is_breached=False,
    )
    assert updated.is_breached is True
    persisted = in_memory_uow.budget_policies.get_for_update("mini-me")
    assert persisted.is_breached is True


def test_reserve_and_standard_settlement_exact_decimal(in_memory_uow):
    in_memory_uow.budget_policies.save(_policy(daily_cap="10.00", monthly_cap="25.00"))
    service = BudgetService(in_memory_uow)
    # prompt: 100 * 0.001 = 0.1, output: 100 * 0.002 = 0.2, add: 0.5 => max = 0.8
    reservation, reason, headroom = service.reserve_budget(
        project_id="mini-me",
        job_id="job-1",
        change_id="change-1",
        role="reviewer",
        canonical_model_identity="qwen:qwen3-coder",
        pricing_snapshot=_snapshot(),
        prompt_token_upper_bound=100,
        max_output_tokens=100,
    )
    assert reason is None
    assert reservation is not None
    assert isinstance(reservation.reserved_amount_usd, Decimal)
    assert reservation.reserved_amount_usd == Decimal("0.800")
    assert reservation.status == "RESERVED"

    # Settle with exact Decimal actual cost 0.500
    settled_entry = service.settle_reservation(
        reservation.reservation_id,
        actual_cost_usd=Decimal("0.500"),
        prompt_tokens=80,
        completion_tokens=60,
        total_tokens=140,
    )
    assert settled_entry is not None
    assert settled_entry.entry_type == "SETTLEMENT"
    assert isinstance(settled_entry.amount_usd, Decimal)
    assert settled_entry.amount_usd == Decimal("0.500")

    updated_res = in_memory_uow.budget_reservations.get_by_id(reservation.reservation_id)
    assert updated_res.status == "SETTLED"

    # Headroom should reflect 0.5 committed, 0 reserved
    _, new_headroom = service.get_headroom("mini-me")
    assert new_headroom.committed_today_usd == Decimal("0.500")
    assert new_headroom.reserved_today_usd == Decimal("0.000")
    assert new_headroom.daily_headroom_usd == Decimal("9.500")


def test_exact_financial_math_without_float_drift(in_memory_uow):
    """Verify that values like 0.1 + 0.2 and 0.000001 per token do not suffer float inaccuracy."""
    # Daily cap $0.30
    in_memory_uow.budget_policies.save(_policy(daily_cap="0.30", monthly_cap="10.00"))
    service = BudgetService(in_memory_uow)

    # 100,000 prompt tokens @ $0.000001 = $0.10, 100,000 output tokens @ $0.000002 = $0.20
    # Exactly $0.30 max cost
    snap = OpenRouterPricingSnapshot(
        snapshot_id="snap-micro",
        canonical_model_identity="anthropic:claude-3.5-sonnet",
        routed_model_identity="anthropic/claude-3.5-sonnet",
        prompt_price_per_token=Decimal("0.000001"),
        output_price_per_token=Decimal("0.000002"),
        additional_cost_per_request=Decimal("0.0"),
    )
    in_memory_uow.pricing_snapshots.save(snap)

    reservation, reason, _ = service.reserve_budget(
        project_id="mini-me",
        job_id="job-micro",
        change_id="change-micro",
        role="implementer",
        canonical_model_identity="anthropic:claude-3.5-sonnet",
        pricing_snapshot=snap,
        prompt_token_upper_bound=100000,
        max_output_tokens=100000,
    )
    assert reason is None
    assert reservation is not None
    assert reservation.reserved_amount_usd == Decimal("0.300000")

    # Settlement exactly at boundary (0.300000) -> must be SETTLED, not BREACH
    entry = service.settle_reservation(
        reservation.reservation_id,
        actual_cost_usd=Decimal("0.300000"),
        prompt_tokens=100000,
        completion_tokens=100000,
        total_tokens=200000,
    )
    assert entry.entry_type == "SETTLEMENT"
    assert in_memory_uow.budget_policies.get_for_update("mini-me").is_breached is False


def test_settlement_breach_detection_exact_boundary(in_memory_uow):
    in_memory_uow.budget_policies.save(_policy())
    service = BudgetService(in_memory_uow)
    # Reserve max 0.800
    reservation, _, _ = service.reserve_budget(
        project_id="mini-me",
        job_id="job-1",
        change_id="change-1",
        role="reviewer",
        canonical_model_identity="qwen:qwen3-coder",
        pricing_snapshot=_snapshot(),
        prompt_token_upper_bound=100,
        max_output_tokens=100,
    )
    assert reservation is not None
    assert reservation.reserved_amount_usd == Decimal("0.800")

    # Settle with actual cost 0.800001 (exceeds reserved 0.800000 by 1 micro-cent) -> BREACH!
    breach_entry = service.settle_reservation(
        reservation.reservation_id,
        actual_cost_usd=Decimal("0.800001"),
        prompt_tokens=150,
        completion_tokens=200,
        total_tokens=350,
    )
    assert breach_entry is not None
    assert breach_entry.entry_type == "BREACH_SETTLEMENT"
    assert breach_entry.amount_usd == Decimal("0.800001")

    updated_res = in_memory_uow.budget_reservations.get_by_id(reservation.reservation_id)
    assert updated_res.status == "SETTLEMENT_BREACH"

    # Policy must be marked breached
    policy = in_memory_uow.budget_policies.get_for_update("mini-me")
    assert policy.is_breached is True

    # Breach detected event emitted with exact Decimal difference
    events = in_memory_uow.events.list_events(project_id="mini-me")
    breach_events = [e for e in events if e.event_type == EventType.BUDGET_BREACH_DETECTED]
    assert len(breach_events) == 1
    assert breach_events[0].payload["breach_amount_usd"] == "0.000001"

    # Subsequent reservation attempt must be denied due to breach
    new_res, new_reason, _ = service.reserve_budget(
        project_id="mini-me",
        job_id="job-2",
        change_id="change-2",
        role="implementer",
        canonical_model_identity="qwen:qwen3-coder",
        pricing_snapshot=_snapshot(),
        prompt_token_upper_bound=10,
        max_output_tokens=10,
    )
    assert new_res is None
    assert new_reason == "policy_denied"


def test_daily_cap_exhaustion_denial(in_memory_uow):
    # Policy with daily cap $1.00
    in_memory_uow.budget_policies.save(_policy(daily_cap="1.00", monthly_cap="10.00"))
    service = BudgetService(in_memory_uow)

    # First reservation takes 0.80
    res1, reason1, _ = service.reserve_budget(
        project_id="mini-me",
        job_id="job-1",
        change_id="change-1",
        role="reviewer",
        canonical_model_identity="qwen:qwen3-coder",
        pricing_snapshot=_snapshot(),
        prompt_token_upper_bound=100,
        max_output_tokens=100,
    )
    assert res1 is not None

    # Second reservation requests 0.80 -> exceeds remaining daily headroom ($0.20)
    res2, reason2, headroom2 = service.reserve_budget(
        project_id="mini-me",
        job_id="job-2",
        change_id="change-2",
        role="reviewer",
        canonical_model_identity="qwen:qwen3-coder",
        pricing_snapshot=_snapshot(),
        prompt_token_upper_bound=100,
        max_output_tokens=100,
    )
    assert res2 is None
    assert reason2 == "budget_denial"
    assert headroom2.daily_headroom_usd == Decimal("0.200")


def test_monthly_cap_exhaustion_denial(in_memory_uow):
    # Daily cap $10.00, monthly cap $1.00
    in_memory_uow.budget_policies.save(_policy(daily_cap="10.00", monthly_cap="1.00"))
    service = BudgetService(in_memory_uow)

    res1, _, _ = service.reserve_budget(
        project_id="mini-me",
        job_id="job-1",
        change_id="change-1",
        role="reviewer",
        canonical_model_identity="qwen:qwen3-coder",
        pricing_snapshot=_snapshot(),
        prompt_token_upper_bound=100,
        max_output_tokens=100,
    )
    assert res1 is not None

    # Second reservation requests 0.80 -> exceeds remaining monthly headroom ($0.20)
    res2, reason2, headroom2 = service.reserve_budget(
        project_id="mini-me",
        job_id="job-2",
        change_id="change-2",
        role="reviewer",
        canonical_model_identity="qwen:qwen3-coder",
        pricing_snapshot=_snapshot(),
        prompt_token_upper_bound=100,
        max_output_tokens=100,
    )
    assert res2 is None
    assert reason2 == "budget_denial"
    assert headroom2.monthly_headroom_usd == Decimal("0.200")


def test_unresolved_reservation_cross_boundary_encumbrance(in_memory_uow):
    in_memory_uow.budget_policies.save(_policy(daily_cap="5.00", monthly_cap="10.00"))
    service = BudgetService(in_memory_uow)

    res, _, _ = service.reserve_budget(
        project_id="mini-me",
        job_id="job-1",
        change_id="change-1",
        role="reviewer",
        canonical_model_identity="qwen:qwen3-coder",
        pricing_snapshot=_snapshot(),
        prompt_token_upper_bound=100,
        max_output_tokens=100,
    )
    assert res is not None

    # Mark unresolved
    unresolved = service.mark_unresolved(res.reservation_id)
    assert unresolved is not None
    assert unresolved.status == "UNRESOLVED"

    # Simulate past date for the unresolved reservation (yesterday / last month)
    unresolved.created_at = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    in_memory_uow.budget_reservations.save(unresolved)

    # Current headroom computation must STILL subtract the full 0.8 unresolved encumbrance
    _, headroom = service.get_headroom("mini-me")
    assert headroom.unresolved_usd == Decimal("0.800")
    assert headroom.daily_headroom_usd == Decimal("4.200")
    assert headroom.monthly_headroom_usd == Decimal("9.200")


def test_multiple_unresolved_accumulate(in_memory_uow):
    in_memory_uow.budget_policies.save(_policy(daily_cap="10.00", monthly_cap="20.00"))
    service = BudgetService(in_memory_uow)

    for i in range(3):
        res, _, _ = service.reserve_budget(
            project_id="mini-me",
            job_id=f"job-{i}",
            change_id=f"change-{i}",
            role="reviewer",
            canonical_model_identity="qwen:qwen3-coder",
            pricing_snapshot=_snapshot(snapshot_id=f"snap-{i}"),
            prompt_token_upper_bound=100,
            max_output_tokens=100,
        )
        service.mark_unresolved(res.reservation_id)

    _, headroom = service.get_headroom("mini-me")
    # 3 * 0.8 = 2.4
    assert headroom.unresolved_usd == Decimal("2.400")
    assert headroom.daily_headroom_usd == Decimal("7.600")
    assert headroom.monthly_headroom_usd == Decimal("17.600")


def test_release_reservation(in_memory_uow):
    in_memory_uow.budget_policies.save(_policy(daily_cap="5.00", monthly_cap="10.00"))
    service = BudgetService(in_memory_uow)

    res, _, _ = service.reserve_budget(
        project_id="mini-me",
        job_id="job-1",
        change_id="change-1",
        role="reviewer",
        canonical_model_identity="qwen:qwen3-coder",
        pricing_snapshot=_snapshot(),
        prompt_token_upper_bound=100,
        max_output_tokens=100,
    )
    assert res is not None
    released = service.release_reservation(res.reservation_id)
    assert released.status == "RELEASED"

    _, headroom = service.get_headroom("mini-me")
    assert headroom.reserved_today_usd == Decimal("0.000")
    assert headroom.daily_headroom_usd == Decimal("5.000")


def test_get_token_usage_breakdown(in_memory_uow):
    in_memory_uow.budget_policies.save(_policy())
    service = BudgetService(in_memory_uow)

    res1, _, _ = service.reserve_budget(
        project_id="mini-me",
        job_id="job-1",
        change_id="change-1",
        role="implementer",
        canonical_model_identity="anthropic:claude-3.5-sonnet",
        pricing_snapshot=_snapshot(
            snapshot_id="snap-claude",
            canonical_model_identity="anthropic:claude-3.5-sonnet",
            routed_model_identity="anthropic/claude-3.5-sonnet",
        ),
        prompt_token_upper_bound=100,
        max_output_tokens=100,
    )
    service.settle_reservation(
        res1.reservation_id,
        actual_cost_usd=Decimal("0.35"),
        prompt_tokens=500,
        completion_tokens=200,
        total_tokens=700,
    )

    res2, _, _ = service.reserve_budget(
        project_id="mini-me",
        job_id="job-2",
        change_id="change-2",
        role="reviewer",
        canonical_model_identity="openai:gpt-4o",
        pricing_snapshot=_snapshot(
            snapshot_id="snap-gpt4o",
            canonical_model_identity="openai:gpt-4o",
            routed_model_identity="openai/gpt-4o",
        ),
        prompt_token_upper_bound=100,
        max_output_tokens=100,
    )
    service.settle_reservation(
        res2.reservation_id,
        actual_cost_usd=Decimal("0.25"),
        prompt_tokens=300,
        completion_tokens=100,
        total_tokens=400,
    )

    breakdown = service.get_token_usage_breakdown("mini-me")
    assert "anthropic:claude-3.5-sonnet" in breakdown
    assert breakdown["anthropic:claude-3.5-sonnet"]["total_tokens"] == 700
    assert breakdown["anthropic:claude-3.5-sonnet"]["amount_usd"] == Decimal("0.35")
    assert "openai:gpt-4o" in breakdown
    assert breakdown["openai:gpt-4o"]["total_tokens"] == 400
    assert breakdown["openai:gpt-4o"]["amount_usd"] == Decimal("0.25")


@pytest.mark.asyncio
async def test_concurrent_reservations_serialization(in_memory_uow):
    """Verify that concurrent reservation requests cannot oversubscribe daily or monthly headroom."""
    # Headroom allows only ONE 0.8 reservation out of $1.00 cap
    in_memory_uow.budget_policies.save(_policy(daily_cap="1.00", monthly_cap="5.00"))
    service = BudgetService(in_memory_uow)

    async def _try_reserve(job_id: str):
        await asyncio.sleep(0.01)
        return service.reserve_budget(
            project_id="mini-me",
            job_id=job_id,
            change_id="change-concurrent",
            role="reviewer",
            canonical_model_identity="qwen:qwen3-coder",
            pricing_snapshot=_snapshot(),
            prompt_token_upper_bound=100,
            max_output_tokens=100,
        )

    results = await asyncio.gather(
        _try_reserve("job-a"),
        _try_reserve("job-b"),
        _try_reserve("job-c"),
        _try_reserve("job-d"),
    )
    successes = [r for r, reason, _ in results if r is not None]
    denials = [reason for r, reason, _ in results if r is None]

    # Exactly 1 can succeed under $1.00 daily cap for $0.80 reservation
    assert len(successes) == 1
    assert len(denials) == 3
    assert all(d == "budget_denial" for d in denials)


def test_reserve_budget_denies_unverified_source(in_memory_uow):
    in_memory_uow.budget_policies.save(_policy(daily_cap="100.00", monthly_cap="1000.00"))
    service = BudgetService(in_memory_uow)

    unverified_sources = ["pinned_default", "heuristic", "inferred", "unknown", ""]
    for src in unverified_sources:
        snap = _snapshot(source=src)
        res, reason, _ = service.reserve_budget(
            project_id="mini-me",
            job_id=f"job-unverified-{src}",
            change_id="change-1",
            role="reviewer",
            canonical_model_identity="qwen:qwen3-coder",
            pricing_snapshot=snap,
            prompt_token_upper_bound=100,
            max_output_tokens=100,
        )
        assert res is None, f"Expected denial for unverified source '{src}'"
        assert reason == "PRICING_UNVERIFIED"


def test_reserve_budget_denies_missing_snapshot(in_memory_uow):
    in_memory_uow.budget_policies.save(_policy(daily_cap="100.00", monthly_cap="1000.00"))
    service = BudgetService(in_memory_uow)
    res, reason, _ = service.reserve_budget(
        project_id="mini-me",
        job_id="job-missing-snap",
        change_id="change-1",
        role="reviewer",
        canonical_model_identity="qwen:qwen3-coder",
        pricing_snapshot=None,
        prompt_token_upper_bound=100,
        max_output_tokens=100,
    )
    assert res is None
    assert reason == "PRICING_SNAPSHOT_MISSING"


def test_reserve_budget_denies_canonical_model_mismatch(in_memory_uow):
    in_memory_uow.budget_policies.save(_policy(daily_cap="100.00", monthly_cap="1000.00"))
    service = BudgetService(in_memory_uow)
    snap = _snapshot(canonical_model_identity="anthropic:claude-3.5-sonnet")
    res, reason, _ = service.reserve_budget(
        project_id="mini-me",
        job_id="job-mismatch",
        change_id="change-1",
        role="reviewer",
        canonical_model_identity="mistral:mistral-large",
        pricing_snapshot=snap,
        prompt_token_upper_bound=100,
        max_output_tokens=100,
    )
    assert res is None
    assert reason == "PRICING_MODEL_MISMATCH"


def test_conservative_maximum_cost_calculation(in_memory_uow):
    in_memory_uow.budget_policies.save(_policy(daily_cap="100.00", monthly_cap="1000.00"))
    service = BudgetService(in_memory_uow)
    snap = _snapshot(
        prompt_price="0.000002",
        output_price="0.000006",
        additional="0.001",
        canonical_model_identity="mistral:mistral-large",
        routed_model_identity="mistralai/mistral-large",
        source="openrouter_catalog_verified",
    )
    prompt_upper = 10000
    max_output = 4096

    res, reason, _ = service.reserve_budget(
        project_id="mini-me",
        job_id="job-mistral",
        change_id="change-1",
        role="reviewer",
        canonical_model_identity="mistral:mistral-large",
        pricing_snapshot=snap,
        prompt_token_upper_bound=prompt_upper,
        max_output_tokens=max_output,
    )
    assert res is not None
    assert reason is None
    expected_cost = Decimal(prompt_upper) * Decimal("0.000002") + Decimal(max_output) * Decimal("0.000006") + Decimal("0.001")
    assert res.reserved_amount_usd == expected_cost
    assert res.reserved_amount_usd == Decimal("0.045576")


def test_all_default_allowed_models_fail_closed_without_verified_snapshot(in_memory_uow):
    in_memory_uow.budget_policies.save(_policy(daily_cap="100.00", monthly_cap="1000.00"))
    service = BudgetService(in_memory_uow)

    default_models = [
        ("anthropic/claude-3.5-sonnet", "anthropic:claude-3.5-sonnet"),
        ("openai/gpt-4o", "openai:gpt-4o"),
        ("meta-llama/llama-3.3-70b-instruct", "meta:llama-3.3-70b-instruct"),
        ("mistralai/mistral-large", "mistral:mistral-large"),
    ]

    for routed_model, canonical_id in default_models:
        # 1. No snapshot supplied -> Denied
        res, reason, _ = service.reserve_budget(
            project_id="mini-me",
            job_id=f"job-no-snap-{routed_model.replace('/', '-')}",
            change_id="change-1",
            role="reviewer",
            canonical_model_identity=canonical_id,
            pricing_snapshot=None,
            prompt_token_upper_bound=1000,
            max_output_tokens=1000,
        )
        assert res is None
        assert reason == "PRICING_SNAPSHOT_MISSING"

        # 2. Pinned default unverified snapshot -> Denied
        unverified_snap = OpenRouterPricingSnapshot(
            snapshot_id=f"snap-unverified-{routed_model.replace('/', '-')}",
            canonical_model_identity=canonical_id,
            routed_model_identity=routed_model,
            prompt_price_per_token=Decimal("0.000001"),
            output_price_per_token=Decimal("0.000002"),
            source="pinned_default",
            observed_at=datetime(2026, 8, 21, tzinfo=UTC),
        )
        res, reason, _ = service.reserve_budget(
            project_id="mini-me",
            job_id=f"job-unverified-{routed_model.replace('/', '-')}",
            change_id="change-1",
            role="reviewer",
            canonical_model_identity=canonical_id,
            pricing_snapshot=unverified_snap,
            prompt_token_upper_bound=1000,
            max_output_tokens=1000,
        )
        assert res is None
        assert reason == "PRICING_UNVERIFIED"

        # 3. Verified exact snapshot -> Succeeded
        verified_snap = OpenRouterPricingSnapshot(
            snapshot_id=f"snap-verified-{routed_model.replace('/', '-')}",
            canonical_model_identity=canonical_id,
            routed_model_identity=routed_model,
            prompt_price_per_token=Decimal("0.000002"),
            output_price_per_token=Decimal("0.000006"),
            source="openrouter_catalog_verified",
            observed_at=datetime(2026, 8, 21, tzinfo=UTC),
        )
        res, reason, _ = service.reserve_budget(
            project_id="mini-me",
            job_id=f"job-verified-{routed_model.replace('/', '-')}",
            change_id="change-1",
            role="reviewer",
            canonical_model_identity=canonical_id,
            pricing_snapshot=verified_snap,
            prompt_token_upper_bound=1000,
            max_output_tokens=1000,
        )
        assert res is not None
        assert reason is None
        assert res.reserved_amount_usd == Decimal("0.008")

