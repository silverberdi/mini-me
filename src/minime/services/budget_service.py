"""Budget policy and reservation service for OpenRouter drain fallback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from minime.domain.enums import EventType
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    BudgetLedgerEntry,
    BudgetReservation,
    Event,
    OpenRouterBudgetPolicy,
    OpenRouterPricingSnapshot,
    utc_now,
)


@dataclass
class BudgetHeadroom:
    daily_cap_usd: Decimal
    monthly_cap_usd: Decimal
    committed_today_usd: Decimal
    committed_month_usd: Decimal
    reserved_today_usd: Decimal
    reserved_month_usd: Decimal
    unresolved_usd: Decimal
    unresolved_count: int
    daily_headroom_usd: Decimal
    monthly_headroom_usd: Decimal


class BudgetService:
    """Authoritative PostgreSQL budget policy guard, reservation, and ledger service."""

    def __init__(self, uow: PersistenceUnitOfWork):
        self.uow = uow

    def sync_policy_from_config(
        self,
        project_id: str,
        enabled: bool,
        daily_cap_usd: Decimal | str | float,
        monthly_cap_usd: Decimal | str | float,
        currency: str = "USD",
        policy_version: int = 1,
        is_breached: bool = False,
    ) -> OpenRouterBudgetPolicy:
        """Synchronize budget policy from configuration while preserving runtime breach state."""
        daily_dec = daily_cap_usd if isinstance(daily_cap_usd, Decimal) else Decimal(str(daily_cap_usd))
        monthly_dec = monthly_cap_usd if isinstance(monthly_cap_usd, Decimal) else Decimal(str(monthly_cap_usd))

        existing = self.uow.budget_policies.get_for_update(project_id)
        effective_is_breached = (existing.is_breached if existing else False) or is_breached
        policy = OpenRouterBudgetPolicy(
            project_id=project_id,
            enabled=enabled,
            daily_cap_usd=daily_dec,
            monthly_cap_usd=monthly_dec,
            currency=currency,
            policy_version=policy_version,
            is_breached=effective_is_breached,
            updated_at=utc_now(),
        )
        self.uow.budget_policies.save(policy)
        return policy

    def get_headroom(self, project_id: str) -> tuple[OpenRouterBudgetPolicy | None, BudgetHeadroom | None]:
        """Compute and return current headroom for a project."""
        policy = self.uow.budget_policies.get_for_update(project_id)
        if not policy:
            return None, None
        return policy, self._compute_headroom(project_id, policy)

    def reserve_budget(
        self,
        *,
        project_id: str,
        job_id: str,
        change_id: str,
        role: str,
        canonical_model_identity: str,
        pricing_snapshot: OpenRouterPricingSnapshot | None,
        prompt_token_upper_bound: int,
        max_output_tokens: int,
        correlation_id: str | None = None,
    ) -> tuple[BudgetReservation | None, str | None, BudgetHeadroom | None]:
        """Atomically evaluate and reserve budget headroom under row-level lock."""
        policy = self.uow.budget_policies.get_for_update(project_id)
        if (
            not policy
            or not policy.enabled
            or policy.is_breached
            or policy.daily_cap_usd <= Decimal("0")
            or policy.monthly_cap_usd <= Decimal("0")
        ):
            return None, "policy_denied", None

        if not pricing_snapshot:
            return None, "PRICING_SNAPSHOT_MISSING", None

        if not getattr(pricing_snapshot, "is_verified", False):
            return None, "PRICING_UNVERIFIED", None

        if pricing_snapshot.canonical_model_identity != canonical_model_identity:
            return None, "PRICING_MODEL_MISMATCH", None

        if prompt_token_upper_bound <= 0 or max_output_tokens <= 0:
            return None, "policy_denied", None

        # Calculate true upper bound maximum request cost using exact Decimal arithmetic
        prompt_cost = Decimal(prompt_token_upper_bound) * pricing_snapshot.prompt_price_per_token
        output_cost = Decimal(max_output_tokens) * pricing_snapshot.output_price_per_token
        add_cost = pricing_snapshot.additional_cost_per_request
        max_cost_dec = prompt_cost + output_cost + add_cost

        headroom = self._compute_headroom(project_id, policy)
        if max_cost_dec > headroom.daily_headroom_usd or max_cost_dec > headroom.monthly_headroom_usd:
            self.uow.events.save(
                Event(
                    event_type=EventType.BUDGET_CAP_EXCEEDED,
                    project_id=project_id,
                    change_id=change_id,
                    operation_id=job_id,
                    payload={
                        "project_id": project_id,
                        "requested_amount_usd": str(max_cost_dec),
                        "daily_headroom_usd": str(headroom.daily_headroom_usd),
                        "monthly_headroom_usd": str(headroom.monthly_headroom_usd),
                    },
                    timestamp=utc_now(),
                )
            )
            return None, "budget_denial", headroom

        reservation = BudgetReservation(
            project_id=project_id,
            job_id=job_id,
            change_id=change_id,
            role=role,
            canonical_model_identity=canonical_model_identity,
            reserved_amount_usd=max_cost_dec,
            status="RESERVED",
            pricing_snapshot_id=pricing_snapshot.snapshot_id,
            correlation_id=correlation_id,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.uow.budget_reservations.save(reservation)
        self.uow.events.save(
            Event(
                event_type=EventType.BUDGET_RESERVED,
                project_id=project_id,
                change_id=change_id,
                operation_id=job_id,
                payload={
                    "reservation_id": reservation.reservation_id,
                    "reserved_amount_usd": str(reservation.reserved_amount_usd),
                    "role": role,
                    "canonical_model_identity": canonical_model_identity,
                },
                timestamp=utc_now(),
            )
        )
        return reservation, None, headroom

    def settle_reservation(
        self,
        reservation_id: str,
        actual_cost_usd: Decimal | str | float,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
    ) -> BudgetLedgerEntry | None:
        """Settle completed reservation against ledger and handle breach if actual > reserved."""
        reservation = self.uow.budget_reservations.get_by_id(reservation_id)
        if not reservation:
            return None

        actual_dec = actual_cost_usd if isinstance(actual_cost_usd, Decimal) else Decimal(str(actual_cost_usd))

        # Check for settlement breach (actual > reserved)
        if actual_dec > reservation.reserved_amount_usd:
            entry = BudgetLedgerEntry(
                reservation_id=reservation.reservation_id,
                project_id=reservation.project_id,
                job_id=reservation.job_id,
                change_id=reservation.change_id,
                provider="openrouter",
                role=reservation.role,
                canonical_model_identity=reservation.canonical_model_identity,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                amount_usd=actual_dec,
                entry_type="BREACH_SETTLEMENT",
                created_at=utc_now(),
            )
            self.uow.budget_ledger.save(entry)

            reservation.status = "SETTLEMENT_BREACH"
            reservation.updated_at = utc_now()
            self.uow.budget_reservations.save(reservation)

            policy = self.uow.budget_policies.get_for_update(reservation.project_id)
            if policy:
                policy.is_breached = True
                policy.updated_at = utc_now()
                self.uow.budget_policies.save(policy)

            breach_diff = actual_dec - reservation.reserved_amount_usd
            self.uow.events.save(
                Event(
                    event_type=EventType.BUDGET_BREACH_DETECTED,
                    project_id=reservation.project_id,
                    change_id=reservation.change_id,
                    operation_id=reservation.job_id,
                    payload={
                        "reservation_id": reservation.reservation_id,
                        "reserved_amount_usd": str(reservation.reserved_amount_usd),
                        "actual_cost_usd": str(actual_dec),
                        "breach_amount_usd": str(breach_diff),
                    },
                    timestamp=utc_now(),
                )
            )
            return entry

        # Standard settlement (actual <= reserved)
        entry = BudgetLedgerEntry(
            reservation_id=reservation.reservation_id,
            project_id=reservation.project_id,
            job_id=reservation.job_id,
            change_id=reservation.change_id,
            provider="openrouter",
            role=reservation.role,
            canonical_model_identity=reservation.canonical_model_identity,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            amount_usd=actual_dec,
            entry_type="SETTLEMENT",
            created_at=utc_now(),
        )
        self.uow.budget_ledger.save(entry)

        reservation.status = "SETTLED"
        reservation.updated_at = utc_now()
        self.uow.budget_reservations.save(reservation)

        released_diff = reservation.reserved_amount_usd - actual_dec
        self.uow.events.save(
            Event(
                event_type=EventType.BUDGET_SETTLED,
                project_id=reservation.project_id,
                change_id=reservation.change_id,
                operation_id=reservation.job_id,
                payload={
                    "reservation_id": reservation.reservation_id,
                    "amount_usd": str(actual_dec),
                    "reserved_amount_usd": str(reservation.reserved_amount_usd),
                    "released_difference_usd": str(released_diff),
                },
                timestamp=utc_now(),
            )
        )
        return entry

    def mark_unresolved(self, reservation_id: str) -> BudgetReservation | None:
        """Mark a dropped/timed-out reservation as UNRESOLVED, retaining 100% encumbrance."""
        reservation = self.uow.budget_reservations.get_by_id(reservation_id)
        if not reservation:
            return None
        reservation.status = "UNRESOLVED"
        reservation.updated_at = utc_now()
        self.uow.budget_reservations.save(reservation)
        return reservation

    def release_reservation(self, reservation_id: str, reason: str = "cancelled") -> BudgetReservation | None:
        """Release a reservation before HTTP dispatch (e.g. pricing changed or cancelled)."""
        reservation = self.uow.budget_reservations.get_by_id(reservation_id)
        if not reservation:
            return None
        reservation.status = "RELEASED"
        reservation.updated_at = utc_now()
        self.uow.budget_reservations.save(reservation)
        return reservation

    def get_token_usage_breakdown(self, project_id: str) -> dict[str, dict[str, Any]]:
        """Calculate aggregate token usage and spend breakdown by canonical model identity."""
        ledger_entries = self.uow.budget_ledger.list_by_project(project_id)
        breakdown: dict[str, dict[str, Any]] = {}
        for e in ledger_entries:
            key = e.canonical_model_identity
            if key not in breakdown:
                breakdown[key] = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "amount_usd": Decimal("0.0"),
                    "call_count": 0,
                }
            breakdown[key]["prompt_tokens"] += e.prompt_tokens or 0
            breakdown[key]["completion_tokens"] += e.completion_tokens or 0
            breakdown[key]["total_tokens"] += e.total_tokens or 0
            breakdown[key]["amount_usd"] += e.amount_usd
            breakdown[key]["call_count"] += 1
        return breakdown

    def _compute_headroom(self, project_id: str, policy: OpenRouterBudgetPolicy) -> BudgetHeadroom:
        """Compute available daily and monthly headroom with all-time unresolved encumbrance."""
        now = utc_now().astimezone(UTC)
        day_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
        month_start = datetime(now.year, now.month, 1, tzinfo=UTC)

        ledger_rows = self.uow.budget_ledger.list_by_project(project_id)
        reservation_rows = self.uow.budget_reservations.list_by_project(project_id)

        committed_today_dec = sum(
            (r.amount_usd for r in ledger_rows if r.created_at >= day_start),
            Decimal("0"),
        )
        committed_month_dec = sum(
            (r.amount_usd for r in ledger_rows if r.created_at >= month_start),
            Decimal("0"),
        )
        reserved_today_dec = sum(
            (
                r.reserved_amount_usd
                for r in reservation_rows
                if r.status == "RESERVED" and r.created_at >= day_start
            ),
            Decimal("0"),
        )
        reserved_month_dec = sum(
            (
                r.reserved_amount_usd
                for r in reservation_rows
                if r.status == "RESERVED" and r.created_at >= month_start
            ),
            Decimal("0"),
        )
        # All-time UNRESOLVED reservations across all past dates
        unresolved_rows = [
            r for r in reservation_rows if r.status == "UNRESOLVED"
        ]
        unresolved_dec = sum(
            (r.reserved_amount_usd for r in unresolved_rows),
            Decimal("0"),
        )
        unresolved_count = len(unresolved_rows)

        daily_cap_dec = policy.daily_cap_usd
        monthly_cap_dec = policy.monthly_cap_usd

        daily_headroom_dec = daily_cap_dec - committed_today_dec - reserved_today_dec - unresolved_dec
        monthly_headroom_dec = monthly_cap_dec - committed_month_dec - reserved_month_dec - unresolved_dec

        return BudgetHeadroom(
            daily_cap_usd=daily_cap_dec,
            monthly_cap_usd=monthly_cap_dec,
            committed_today_usd=committed_today_dec,
            committed_month_usd=committed_month_dec,
            reserved_today_usd=reserved_today_dec,
            reserved_month_usd=reserved_month_dec,
            unresolved_usd=unresolved_dec,
            unresolved_count=unresolved_count,
            daily_headroom_usd=daily_headroom_dec,
            monthly_headroom_usd=monthly_headroom_dec,
        )
