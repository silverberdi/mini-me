"""Budget policy and reservation service for OpenRouter drain fallback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from minime.domain.enums import EventType
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    BudgetLedgerEntry,
    BudgetReservation,
    Event,
    OpenRouterBudgetPolicy,
    OpenRouterPricingSnapshot,
    Review,
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


@dataclass(frozen=True)
class UnreservedCodeReviewUsageAudit:
    """Identity-only attribution for direct CODE_REVIEW usage without a reservation.

    Ledger timestamps are deliberately not considered: the usage row ID is the
    deterministic idempotency identity derived from the Review ID.
    """

    attributed_reviews: dict[str, Review]
    unresolved_entries: tuple[BudgetLedgerEntry, ...]
    complete: bool = True


class BudgetService:
    """Authoritative PostgreSQL budget policy guard, reservation, and ledger service."""

    def __init__(self, uow: PersistenceUnitOfWork):
        self.uow = uow

    def get_verified_review_price_snapshot(
        self, *, provider: str, account_fingerprint: str, model: str, billing_origin: str
    ):
        """Resolve an exact direct-account pricing snapshot without OpenRouter fallback."""
        snapshots = self.uow.pricing_snapshots.list_by_model(model)
        now = utc_now()
        eligible = [
            item
            for item in snapshots
            if item.is_verified
            and item.provider == provider
            and item.account_fingerprint == account_fingerprint
            and item.canonical_model_identity == model
            and item.billing_origin == billing_origin
            and item.currency == "USD"
            and item.observed_at.tzinfo is not None
            and item.observed_at <= now
            and (now - item.observed_at).total_seconds() <= 30 * 86400
        ]
        return max(eligible, key=lambda item: item.observed_at, default=None)

    def audit_unreserved_code_review_usage(
        self, *, project_id: str, job_id: str
    ) -> UnreservedCodeReviewUsageAudit:
        """Attribute unreserved DeepSeek CODE_REVIEW rows to exact terminal Reviews.

        A missing Review, malformed usage identity, mismatched Review, or
        contradictory completed authorization remains unresolved. This narrow
        audit is shared by reconciliation, authorization renewal and spending
        exposure so those gates cannot disagree about orphaned direct usage.
        """
        reviews_repo = getattr(self.uow, "reviews", None)
        ledger_repo = getattr(self.uow, "budget_ledger", None)
        if reviews_repo is None or ledger_repo is None:
            return UnreservedCodeReviewUsageAudit({}, (), complete=False)

        reviews = {
            review.review_id: review
            for review in reviews_repo.list_by_job(job_id)
            if review.project_id == project_id
            and review.job_id == job_id
            and review.review_stage == "CODE_REVIEW"
        }
        attributed: dict[str, Review] = {}
        unresolved: list[BudgetLedgerEntry] = []
        for entry in ledger_repo.list_by_project(project_id):
            if not (
                entry.project_id == project_id
                and entry.job_id == job_id
                and entry.stage == "REVIEW"
                and entry.entry_type == "USAGE"
                and entry.reservation_id is None
                and (entry.provider == "deepseek" or entry.billing_origin == "deepseek_direct")
            ):
                continue
            # Resolve by the documented deterministic idempotency mapping, not
            # by approximate timestamps, amount, or payload similarity.
            matching_reviews = [
                review
                for review in reviews.values()
                if str(uuid5(NAMESPACE_URL, f"minime:review-usage:v1:{review.review_id}"))
                == entry.entry_id
            ]
            if len(matching_reviews) != 1:
                unresolved.append(entry)
                continue
            review = matching_reviews[0]
            tokens_valid = (
                isinstance(entry.prompt_tokens, int)
                and not isinstance(entry.prompt_tokens, bool)
                and entry.prompt_tokens >= 0
                and isinstance(entry.completion_tokens, int)
                and not isinstance(entry.completion_tokens, bool)
                and entry.completion_tokens >= 0
                and isinstance(entry.total_tokens, int)
                and not isinstance(entry.total_tokens, bool)
                and entry.total_tokens == entry.prompt_tokens + entry.completion_tokens
            )
            try:
                amount_valid = entry.amount_usd.is_finite() and entry.amount_usd >= 0
            except (AttributeError, TypeError):
                amount_valid = False
            if not (
                entry.provider == "deepseek"
                and entry.billing_origin == "deepseek_direct"
                and entry.change_id == review.change_name
                and entry.role == "reviewer"
                and entry.account_fingerprint
                and entry.account_fingerprint == review.account_fingerprint
                and entry.canonical_model_identity
                and entry.canonical_model_identity == review.reviewer_model
                and review.provider == "deepseek"
                and review.reviewer_role == "deepseek"
                and review.billing_origin == "deepseek_direct"
                and review.budget_reservation_id is None
                and review.status.value in {"REVIEW_COMPLETED", "REVIEW_FAILED"}
                and review.orchestration_run_id
                and review.candidate_sha
                and review.base_sha
                and tokens_valid
                and amount_valid
            ):
                unresolved.append(entry)
                continue
            runs_repo = getattr(self.uow, "orchestration_runs", None)
            jobs_repo = getattr(self.uow, "jobs", None)
            candidates_repo = getattr(self.uow, "orchestration_candidates", None)
            manifests_repo = getattr(self.uow, "candidate_manifests", None)
            run = (
                runs_repo.get_by_id(review.orchestration_run_id) if runs_repo is not None else None
            )
            job = jobs_repo.get_by_id(job_id) if jobs_repo is not None else None
            candidate = (
                candidates_repo.get_by_generation(
                    review.orchestration_run_id, review.candidate_generation
                )
                if candidates_repo is not None and review.candidate_generation is not None
                else None
            )
            manifest = (
                manifests_repo.get_by_id(review.manifest_id)
                if manifests_repo is not None and review.manifest_id
                else None
            )
            if not (
                run
                and run.project_id == project_id
                and run.change_name == review.change_name
                and job
                and job.project_id == project_id
                and job.change_name == review.change_name
                and candidate
                and candidate.run_id == review.orchestration_run_id
                and candidate.generation == review.candidate_generation
                and candidate.candidate_sha == review.candidate_sha
                and candidate.base_sha == review.base_sha
                and candidate.manifest_id == review.manifest_id
                and candidate.manifest_hash == review.manifest_hash
                and manifest
                and manifest.job_id == job_id
                and manifest.candidate_sha == review.candidate_sha
                and manifest.manifest_id == review.manifest_id
                and manifest.manifest_hash == review.manifest_hash
            ):
                unresolved.append(entry)
                continue
            if review.budget_authorization_id:
                action_repo = getattr(self.uow, "operator_actions", None)
                action = (
                    action_repo.get_by_request_id(review.budget_authorization_id)
                    if action_repo is not None
                    else None
                )
                authorization = (
                    action.result_payload_json.get("authorization", {}) if action else {}
                )
                if not (
                    action
                    and action.action_type.value == "AUTHORIZE_DEEPSEEK_CODE_REVIEW"
                    and action.status.value == "COMPLETED"
                    and action.project_id == project_id
                    and action.job_id == job_id
                    and action.run_id == review.orchestration_run_id
                    and authorization.get("action_request_id") == action.action_request_id
                    and authorization.get("run_id") == review.orchestration_run_id
                    and authorization.get("job_id") == job_id
                    and authorization.get("candidate_sha") == review.candidate_sha
                    and authorization.get("base_sha") == review.base_sha
                    and authorization.get("generation") == review.candidate_generation
                    and authorization.get("manifest_id") == review.manifest_id
                    and authorization.get("manifest_hash") == review.manifest_hash
                    and authorization.get("provider") == "deepseek"
                    and authorization.get("stage") == "REVIEW"
                    and authorization.get("billing_origin") == "deepseek_direct"
                    and authorization.get("account_fingerprint") == entry.account_fingerprint
                    and authorization.get("model") == entry.canonical_model_identity
                ):
                    unresolved.append(entry)
                    continue
            attributed[entry.entry_id] = review
        return UnreservedCodeReviewUsageAudit(attributed, tuple(unresolved))

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
        daily_dec = (
            daily_cap_usd if isinstance(daily_cap_usd, Decimal) else Decimal(str(daily_cap_usd))
        )
        monthly_dec = (
            monthly_cap_usd
            if isinstance(monthly_cap_usd, Decimal)
            else Decimal(str(monthly_cap_usd))
        )

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

    def get_headroom(
        self, project_id: str
    ) -> tuple[OpenRouterBudgetPolicy | None, BudgetHeadroom | None]:
        """Compute and return current headroom for a project."""
        repo = getattr(self.uow, "budget_policies", None)
        if repo is None:
            return None, None
        policy = repo.get_for_update(project_id)
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
        if (
            max_cost_dec > headroom.daily_headroom_usd
            or max_cost_dec > headroom.monthly_headroom_usd
        ):
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

    def reserve_review_budget(
        self,
        *,
        project_id: str,
        run_id: str,
        job_id: str,
        change_id: str,
        provider: str,
        account_fingerprint: str,
        model: str,
        stage: str,
        billing_origin: str,
        pricing_snapshot_id: str,
        prompt_token_upper_bound: int,
        max_output_tokens: int,
        idempotency_key: str,
        candidate_sha: str | None = None,
        candidate_generation: int | None = None,
        manifest_id: str | None = None,
        manifest_hash: str | None = None,
        maximum_stage_usd: Decimal | str | None = None,
        maximum_combined_usd: Decimal | str | None = None,
        authorization_id: str | None = None,
    ) -> tuple[BudgetReservation | None, str | None]:
        """Enforce optional owner-configured DeepSeek review limits.

        A missing limit means ordinary owner-authorized autonomous operation, not
        missing per-call approval.  When a limit is configured, this reserves its
        conservative upper bound before dispatch.
        """
        if provider != "deepseek" or stage not in {"CONTRACT_REVIEW", "REVIEW"}:
            return None, "REVIEW_PROVIDER_OR_STAGE_DENIED"
        existing = self.uow.budget_reservations.get_by_idempotency_key(idempotency_key)
        if existing:
            exact = (
                existing.project_id == project_id
                and existing.run_id == run_id
                and existing.job_id == job_id
                and existing.provider == provider
                and existing.account_fingerprint == account_fingerprint
                and existing.canonical_model_identity == model
                and existing.stage == stage
                and existing.billing_origin == billing_origin
                and existing.authorization_id == authorization_id
            )
            if exact and existing.status == "RESERVED":
                return existing, None
            return None, "REVIEW_RESERVATION_ALREADY_CONSUMED_OR_CONFLICTING"

        if stage == "REVIEW" and not (
            candidate_sha and manifest_id and manifest_hash and candidate_generation is not None
        ):
            return None, "CODE_REVIEW_CANDIDATE_IDENTITY_MISSING"

        snapshot = self.uow.pricing_snapshots.get_by_id(pricing_snapshot_id)
        if (
            not snapshot
            or not snapshot.is_verified
            or snapshot.provider != provider
            or snapshot.account_fingerprint != account_fingerprint
            or snapshot.canonical_model_identity != model
            or snapshot.billing_origin != billing_origin
            or snapshot.currency != "USD"
            or snapshot.observed_at.tzinfo is None
            or snapshot.observed_at > utc_now()
            or (utc_now() - snapshot.observed_at).total_seconds() > 30 * 86400
        ):
            return None, "VERIFIED_PROVIDER_PRICE_MISSING_OR_MISMATCHED"
        if prompt_token_upper_bound <= 0 or max_output_tokens <= 0:
            return None, "REVIEW_COST_BOUND_INVALID"

        max_cost = (
            Decimal(prompt_token_upper_bound) * snapshot.prompt_price_per_token
            + Decimal(max_output_tokens) * snapshot.output_price_per_token
            + snapshot.additional_cost_per_request
        )
        stage_limit = self._optional_limit(maximum_stage_usd)
        combined_limit = self._optional_limit(maximum_combined_usd)
        if maximum_stage_usd is not None and stage_limit is None:
            return None, "REVIEW_STAGE_LIMIT_INVALID"
        if maximum_combined_usd is not None and combined_limit is None:
            return None, "REVIEW_COMBINED_LIMIT_INVALID"
        if max_cost <= 0:
            return None, "REVIEW_COST_BOUND_INVALID"
        if stage_limit is None and combined_limit is None:
            return None, None

        stage_exposure, combined_exposure = self._direct_review_exposure(
            project_id=project_id,
            stage=stage,
        )
        if stage_limit is not None and stage_exposure + max_cost > stage_limit:
            return None, "REVIEW_STAGE_SPENDING_LIMIT_EXCEEDED"
        if combined_limit is not None and combined_exposure + max_cost > combined_limit:
            return None, "REVIEW_COMBINED_SPENDING_LIMIT_EXCEEDED"

        reservation = BudgetReservation(
            project_id=project_id,
            job_id=job_id,
            run_id=run_id,
            change_id=change_id,
            role="reviewer",
            canonical_model_identity=model,
            reserved_amount_usd=max_cost,
            status="RESERVED",
            pricing_snapshot_id=snapshot.snapshot_id,
            # The idempotency key is already a bounded digest over the exact
            # Run/Job/stage/candidate/manifest identity. Reuse it as the durable
            # correlation ID so CODE_REVIEW cannot exceed the VARCHAR(128)
            # schema bound with raw SHA and manifest values.
            correlation_id=idempotency_key,
            provider=provider,
            account_fingerprint=account_fingerprint,
            stage=stage,
            billing_origin=billing_origin,
            authorization_id=authorization_id,
            idempotency_key=idempotency_key,
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
                    "authorization_id": authorization_id,
                    "provider": provider,
                    "account_fingerprint": account_fingerprint,
                    "model": model,
                    "stage": stage,
                    "billing_origin": billing_origin,
                    "reserved_amount_usd": str(max_cost),
                },
                timestamp=utc_now(),
            )
        )
        return reservation, None

    @staticmethod
    def _optional_limit(value: Decimal | str | None) -> Decimal | None:
        if value is None:
            return None
        try:
            amount = value if isinstance(value, Decimal) else Decimal(str(value))
        except Exception:
            return None
        return amount if amount.is_finite() and amount > 0 else None

    def _direct_review_exposure(self, *, project_id: str, stage: str) -> tuple[Decimal, Decimal]:
        """Return project-wide direct-DeepSeek exposure, counting unresolved conservatively."""
        reservations = [
            item
            for item in self.uow.budget_reservations.list_by_project(project_id)
            if (item.provider == "deepseek" or item.billing_origin == "deepseek_direct")
            and item.stage in {"CONTRACT_REVIEW", "REVIEW"}
        ]
        ledger = [
            item
            for item in self.uow.budget_ledger.list_by_project(project_id)
            if (item.provider == "deepseek" or item.billing_origin == "deepseek_direct")
            and item.stage in {"CONTRACT_REVIEW", "REVIEW"}
        ]
        # The same identity audit used by authorization and recovery is applied
        # here. It never associates usage to a grant by time: attributed and
        # orphaned usage both remain financial exposure, while the orphan is
        # left unassigned to any authorization.
        unreserved_code_review_jobs = {
            item.job_id for item in ledger if item.stage == "REVIEW" and item.reservation_id is None
        }
        usage_audits = {
            job_id: self.audit_unreserved_code_review_usage(project_id=project_id, job_id=job_id)
            for job_id in unreserved_code_review_jobs
        }
        unresolved_usage_ids = {
            entry.entry_id for audit in usage_audits.values() for entry in audit.unresolved_entries
        }
        attributed_usage_ids = {
            entry_id for audit in usage_audits.values() for entry_id in audit.attributed_reviews
        }
        ledger_by_reservation: dict[str, Decimal] = {}
        unreserved_by_stage = {"CONTRACT_REVIEW": Decimal("0"), "REVIEW": Decimal("0")}
        for entry in ledger:
            if entry.reservation_id:
                ledger_by_reservation[entry.reservation_id] = (
                    ledger_by_reservation.get(entry.reservation_id, Decimal("0")) + entry.amount_usd
                )
            else:
                try:
                    amount = entry.amount_usd
                    if not amount.is_finite() or amount < 0:
                        amount = Decimal("Infinity")
                except (AttributeError, TypeError):
                    amount = Decimal("Infinity")
                if entry.stage == "REVIEW":
                    if entry.entry_id in unresolved_usage_ids:
                        # Preserve the verified ledger amount as unassigned
                        # spend; never infer which authorization paid it.
                        unreserved_by_stage["REVIEW"] += amount
                    elif entry.entry_id in attributed_usage_ids:
                        # A distinct operation is recognized by the exact
                        # Review-derived idempotency key, never by timestamp.
                        unreserved_by_stage["REVIEW"] += amount
                    else:
                        # Non-USAGE legacy entries are still counted, but are
                        # not eligible for attribution by this audit.
                        unreserved_by_stage["REVIEW"] += amount
                else:
                    unreserved_by_stage[entry.stage] += amount
        stage_total = Decimal("0")
        combined_total = sum(unreserved_by_stage.values(), Decimal("0"))
        if stage in unreserved_by_stage:
            stage_total = unreserved_by_stage[stage]
        for item in reservations:
            actual = ledger_by_reservation.get(item.reservation_id)
            if item.status in {"RESERVED", "UNRESOLVED"}:
                exposure = max(item.reserved_amount_usd, actual or Decimal("0"))
            elif actual is not None:
                exposure = actual
            elif item.status in {"SETTLED", "SETTLEMENT_BREACH"}:
                exposure = item.reserved_amount_usd
            else:
                exposure = Decimal("0")
            combined_total += exposure
            if item.stage == stage:
                stage_total += exposure
        for entry in ledger:
            if not entry.reservation_id:
                continue
            if not any(item.reservation_id == entry.reservation_id for item in reservations):
                combined_total += entry.amount_usd
                if entry.stage == stage:
                    stage_total += entry.amount_usd
        return stage_total, combined_total

    def record_unreserved_review_usage(
        self,
        *,
        project_id: str,
        job_id: str,
        change_id: str,
        provider: str,
        account_fingerprint: str,
        model: str,
        stage: str,
        billing_origin: str,
        review_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        actual_cost_usd: Decimal,
    ) -> BudgetLedgerEntry:
        """Idempotently account verified provider usage when no cap is configured."""
        entry_id = str(uuid5(NAMESPACE_URL, f"minime:review-usage:v1:{review_id}"))
        existing = next(
            (
                item
                for item in self.uow.budget_ledger.list_by_project(project_id)
                if item.entry_id == entry_id
            ),
            None,
        )
        if existing:
            if (
                existing.job_id != job_id
                or existing.provider != provider
                or existing.account_fingerprint != account_fingerprint
                or existing.canonical_model_identity != model
                or existing.stage != stage
                or existing.billing_origin != billing_origin
                or existing.prompt_tokens != prompt_tokens
                or existing.completion_tokens != completion_tokens
                or existing.amount_usd != actual_cost_usd
            ):
                raise ValueError("review usage idempotency identity conflicts")
            return existing
        entry = BudgetLedgerEntry(
            entry_id=entry_id,
            project_id=project_id,
            job_id=job_id,
            change_id=change_id,
            provider=provider,
            account_fingerprint=account_fingerprint,
            stage=stage,
            billing_origin=billing_origin,
            role="reviewer",
            canonical_model_identity=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            amount_usd=actual_cost_usd,
            entry_type="USAGE",
        )
        self.uow.budget_ledger.save(entry)
        self.uow.events.save(
            Event(
                event_type=EventType.BUDGET_SETTLED,
                project_id=project_id,
                change_id=change_id,
                operation_id=job_id,
                payload={
                    "review_id": review_id,
                    "usage_entry_id": entry_id,
                    "provider": provider,
                    "account_fingerprint": account_fingerprint,
                    "model": model,
                    "stage": stage,
                    "billing_origin": billing_origin,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "amount_usd": str(actual_cost_usd),
                },
                timestamp=utc_now(),
            )
        )
        return entry

    def settle_reservation(
        self,
        reservation_id: str,
        actual_cost_usd: Decimal | str | float,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
    ) -> BudgetLedgerEntry | None:
        """Settle completed reservation against ledger and handle breach if actual > reserved."""
        reservation = getattr(
            self.uow.budget_reservations,
            "get_by_id_for_update",
            self.uow.budget_reservations.get_by_id,
        )(reservation_id)
        if not reservation or reservation.status != "RESERVED":
            return None

        actual_dec = (
            actual_cost_usd
            if isinstance(actual_cost_usd, Decimal)
            else Decimal(str(actual_cost_usd))
        )
        if not actual_dec.is_finite() or actual_dec < 0:
            return None
        if any(
            value is not None and value < 0
            for value in (prompt_tokens, completion_tokens, total_tokens)
        ):
            return None

        # Check for settlement breach (actual > reserved)
        if actual_dec > reservation.reserved_amount_usd:
            entry = BudgetLedgerEntry(
                reservation_id=reservation.reservation_id,
                project_id=reservation.project_id,
                job_id=reservation.job_id,
                change_id=reservation.change_id,
                provider=reservation.provider,
                account_fingerprint=reservation.account_fingerprint,
                stage=reservation.stage,
                billing_origin=reservation.billing_origin,
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

            policy = (
                self.uow.budget_policies.get_for_update(reservation.project_id)
                if reservation.provider == "openrouter"
                else None
            )
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
                        "provider": reservation.provider,
                        "stage": reservation.stage,
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
            provider=reservation.provider,
            account_fingerprint=reservation.account_fingerprint,
            stage=reservation.stage,
            billing_origin=reservation.billing_origin,
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
                    "authorization_id": reservation.authorization_id,
                    "provider": reservation.provider,
                    "account_fingerprint": reservation.account_fingerprint,
                    "model": reservation.canonical_model_identity,
                    "stage": reservation.stage,
                    "billing_origin": reservation.billing_origin,
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

    def settle_unproductive_reservation(
        self,
        reservation_id: str,
        actual_cost_usd: Decimal | str | float,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
    ) -> BudgetLedgerEntry | None:
        """Record actual provider cost truthfully but leave the reservation unresolved.

        Used when a provider call physically occurred and consumed money but
        produced no material repository work (e.g. OpenRouter textual success with
        no repository-editing harness). The spend is real and is recorded; the
        reservation is NOT settled as a successful completion.
        """
        reservation = getattr(
            self.uow.budget_reservations,
            "get_by_id_for_update",
            self.uow.budget_reservations.get_by_id,
        )(reservation_id)
        if not reservation or reservation.status != "RESERVED":
            return None

        actual_dec = (
            actual_cost_usd
            if isinstance(actual_cost_usd, Decimal)
            else Decimal(str(actual_cost_usd))
        )
        if not actual_dec.is_finite() or actual_dec < 0:
            return None
        if any(
            value is not None and value < 0
            for value in (prompt_tokens, completion_tokens, total_tokens)
        ):
            return None

        entry = BudgetLedgerEntry(
            reservation_id=reservation.reservation_id,
            project_id=reservation.project_id,
            job_id=reservation.job_id,
            change_id=reservation.change_id,
            provider=reservation.provider,
            account_fingerprint=reservation.account_fingerprint,
            stage=reservation.stage,
            billing_origin=reservation.billing_origin,
            role=reservation.role,
            canonical_model_identity=reservation.canonical_model_identity,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            amount_usd=actual_dec,
            entry_type="UNPRODUCTIVE_SETTLEMENT",
            created_at=utc_now(),
        )
        self.uow.budget_ledger.save(entry)

        reservation.status = "UNRESOLVED"
        reservation.updated_at = utc_now()
        self.uow.budget_reservations.save(reservation)

        self.uow.events.save(
            Event(
                event_type=EventType.BUDGET_SETTLED,
                project_id=reservation.project_id,
                change_id=reservation.change_id,
                operation_id=reservation.job_id,
                payload={
                    "reservation_id": reservation.reservation_id,
                    "authorization_id": reservation.authorization_id,
                    "provider": reservation.provider,
                    "account_fingerprint": reservation.account_fingerprint,
                    "model": reservation.canonical_model_identity,
                    "stage": reservation.stage,
                    "billing_origin": reservation.billing_origin,
                    "amount_usd": str(actual_dec),
                    "outcome": "UNPRODUCTIVE",
                    "note": (
                        "Provider cost incurred but no repository materialization "
                        "delivered; reservation left unresolved."
                    ),
                },
                timestamp=utc_now(),
            )
        )
        return entry

    def release_reservation(
        self, reservation_id: str, reason: str = "cancelled"
    ) -> BudgetReservation | None:
        """Release a reservation before HTTP dispatch (e.g. pricing changed or cancelled)."""
        reservation = getattr(
            self.uow.budget_reservations,
            "get_by_id_for_update",
            self.uow.budget_reservations.get_by_id,
        )(reservation_id)
        if not reservation or reservation.status != "RESERVED":
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
        # The legacy project budget remains an OpenRouter authority. Direct
        # provider spend is charged to its own account/stage authorization and
        # must neither consume nor breach OpenRouter's historical headroom.
        ledger_rows = [r for r in ledger_rows if r.provider == "openrouter"]
        reservation_rows = [r for r in reservation_rows if r.provider == "openrouter"]

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
        unresolved_rows = [r for r in reservation_rows if r.status == "UNRESOLVED"]
        unresolved_dec = sum(
            (r.reserved_amount_usd for r in unresolved_rows),
            Decimal("0"),
        )
        unresolved_count = len(unresolved_rows)

        daily_cap_dec = policy.daily_cap_usd
        monthly_cap_dec = policy.monthly_cap_usd

        daily_headroom_dec = (
            daily_cap_dec - committed_today_dec - reserved_today_dec - unresolved_dec
        )
        monthly_headroom_dec = (
            monthly_cap_dec - committed_month_dec - reserved_month_dec - unresolved_dec
        )

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
