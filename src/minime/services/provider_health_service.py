from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

from minime.adapters.provider_adapter import get_provider_adapter
from minime.config import ProbeConfig, load_config, probe_configs_from_app_config
from minime.domain.enums import (
    PRIMARY_PROVIDERS,
    CapacitySignalSource,
    EventType,
    ProviderHealthStatus,
    ProviderResultClass,
)
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    CapacityWindow,
    Event,
    NormalizedProviderResult,
    ProviderHealth,
    utc_now,
)

logger = logging.getLogger(__name__)


class ProviderHealthService:
    """Manages primary and generic provider health, exhaustion windows, and probe verification."""

    def __init__(
        self,
        uow: PersistenceUnitOfWork,
        failure_threshold: int = 3,
        probe_config: ProbeConfig | None = None,
        probe_configs: dict[str, ProbeConfig] | None = None,
    ):
        self.uow = uow
        self.failure_threshold = failure_threshold
        self.probe_config = probe_config
        self.probe_configs = self._resolve_probe_configs(probe_config, probe_configs)
        self._probe_locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def _resolve_probe_configs(
        probe_config: ProbeConfig | None,
        probe_configs: dict[str, ProbeConfig] | None,
    ) -> dict[str, ProbeConfig]:
        """Resolve per-provider probe policies.

        An explicit ``probe_configs`` wins outright. An explicit process-wide
        ``probe_config`` suppresses app-config auto-wiring (embedded callers/tests
        own their probe policy). Otherwise, derive per-provider policies from the
        operator's app config so YAML ``probe:`` blocks actually govern runtime.
        """
        if probe_configs is not None:
            return probe_configs
        if probe_config is not None:
            return {}
        try:
            return probe_configs_from_app_config(load_config())
        except Exception:
            logger.warning(
                "Failed to derive probe configs from app config; using defaults.",
                exc_info=True,
            )
            return {}

    def _validate_primary(self, provider: str) -> None:
        # Generic providers are permitted as long as they are non-empty strings
        if not provider or not isinstance(provider, str):
            raise ValueError(f"Invalid provider '{provider}'. Must be a non-empty string.")

    def get_health(self, provider: str) -> ProviderHealth:
        """Get or initialize health record for a provider."""
        self._validate_primary(provider)
        health = self.uow.provider_health.get_by_provider(provider)
        if not health:
            health = ProviderHealth(
                health_id=f"ph-{provider}",
                provider=provider,
                status=ProviderHealthStatus.AVAILABLE,
                consecutive_failures=0,
                updated_at=utc_now(),
            )
            self.uow.provider_health.save(health)
            self.uow.commit()
        return health

    def list_all_health(self) -> list[ProviderHealth]:
        """List health for all tracked providers, ensuring records exist."""
        results = []
        for prov in sorted(PRIMARY_PROVIDERS):
            results.append(self.get_health(prov))
        return results

    def list_all_health_with_capacity(self) -> list[tuple[ProviderHealth, CapacityWindow | None]]:
        """Return health with its authoritative latest capacity window."""
        return [
            (health, self.uow.capacity_windows.get_latest_for_provider(health.provider))
            for health in self.list_all_health()
        ]

    def set_operator_expected_reset(
        self, provider: str, reset_at: datetime
    ) -> CapacityWindow:
        """Record an operator-reported expected provider recovery time."""
        self._validate_primary(provider)
        now = utc_now()
        if reset_at.tzinfo is None:
            reset_at = reset_at.replace(tzinfo=UTC)

        window = CapacityWindow(
            provider=provider,
            quota_exhausted_at=now,
            capacity_reset_at=reset_at,
            source_signal=CapacitySignalSource.OPERATOR_REPORTED,
            created_at=now,
        )
        self.uow.capacity_windows.save(window)
        self.uow.events.save(
            Event(
                event_type=EventType.PROVIDER_HEALTH_UPDATED,
                payload={
                    "provider": provider,
                    "reset_source": "OPERATOR_REPORTED",
                    "capacity_reset_at": reset_at.isoformat(),
                },
                timestamp=now,
            )
        )
        self.uow.commit()
        return window

    def record_outcome(
        self,
        outcome: NormalizedProviderResult,
    ) -> ProviderHealth:
        """Record an operation outcome and update health/capacity states accordingly."""
        self._validate_primary(outcome.provider)
        current = self.get_health(outcome.provider)
        now = utc_now()
        prev_status = current.status

        if outcome.result_class == ProviderResultClass.SUCCESS:
            # Clean success resets consecutive failures and restores AVAILABLE status
            new_health = self.uow.provider_health.update_health(
                provider=outcome.provider,
                status=ProviderHealthStatus.AVAILABLE.value,
                result_class=outcome.result_class.value,
                error_summary=outcome.summary,
                consecutive_failures=0,
            )
            if prev_status != ProviderHealthStatus.AVAILABLE:
                self.uow.events.save(
                    Event(
                        event_type=EventType.PRIMARY_CAPACITY_RECOVERED,
                        payload={
                            "provider": outcome.provider,
                            "role": outcome.role,
                            "previous_status": prev_status.value,
                            "new_status": ProviderHealthStatus.AVAILABLE.value,
                        },
                        timestamp=now,
                    )
                )
            self.uow.commit()
            return new_health

        elif outcome.result_class in {
            ProviderResultClass.QUOTA_LIMIT,
            ProviderResultClass.RATE_LIMIT,
        }:
            # Quota or rate limit exhaustion
            target_status = (
                ProviderHealthStatus.EXHAUSTED
                if outcome.result_class == ProviderResultClass.QUOTA_LIMIT
                else ProviderHealthStatus.TEMPORARILY_UNAVAILABLE
            )
            new_health = self.uow.provider_health.update_health(
                provider=outcome.provider,
                status=target_status.value,
                result_class=outcome.result_class.value,
                error_summary=outcome.summary,
                consecutive_failures=current.consecutive_failures + 1,
            )

            # Record capacity window
            retry_secs = None
            if outcome.retry_after:
                try:
                    retry_secs = int(outcome.retry_after)
                except ValueError:
                    pass

            signal_source = CapacitySignalSource.UNKNOWN
            if outcome.retry_after:
                signal_source = CapacitySignalSource.HEADER_RETRY_AFTER
            elif outcome.capacity_reset_at:
                signal_source = CapacitySignalSource.RESPONSE_BODY_TIMESTAMP

            window = CapacityWindow(
                provider=outcome.provider,
                model=outcome.model,
                quota_exhausted_at=now,
                capacity_reset_at=outcome.capacity_reset_at,
                retry_after_seconds=retry_secs,
                source_signal=signal_source,
                created_at=now,
            )
            self.uow.capacity_windows.save(window)

            self.uow.events.save(
                Event(
                    event_type=EventType.PRIMARY_CAPACITY_EXHAUSTED,
                    payload={
                        "provider": outcome.provider,
                        "role": outcome.role,
                        "result_class": outcome.result_class.value,
                        "capacity_reset_at": outcome.capacity_reset_at.isoformat()
                        if outcome.capacity_reset_at
                        else None,
                        "retry_after_seconds": retry_secs,
                        "summary": outcome.summary,
                    },
                    timestamp=now,
                )
            )
            self.uow.commit()
            return new_health

        elif outcome.result_class == ProviderResultClass.AUTH_ERROR:
            new_health = self.uow.provider_health.update_health(
                provider=outcome.provider,
                status=ProviderHealthStatus.AUTH_REQUIRED.value,
                result_class=outcome.result_class.value,
                error_summary=outcome.summary,
                consecutive_failures=current.consecutive_failures + 1,
            )
            self.uow.events.save(
                Event(
                    event_type=EventType.PROVIDER_HEALTH_UPDATED,
                    payload={
                        "provider": outcome.provider,
                        "status": ProviderHealthStatus.AUTH_REQUIRED.value,
                        "result_class": outcome.result_class.value,
                        "summary": outcome.summary,
                    },
                    timestamp=now,
                )
            )
            self.uow.commit()
            return new_health

        else:
            # Transient error, timeout, malformed, or unknown error
            new_failures = current.consecutive_failures + 1
            target_status = current.status
            if new_failures >= self.failure_threshold:
                target_status = ProviderHealthStatus.TEMPORARILY_UNAVAILABLE

            new_health = self.uow.provider_health.update_health(
                provider=outcome.provider,
                status=target_status.value,
                result_class=outcome.result_class.value,
                error_summary=outcome.summary,
                consecutive_failures=new_failures,
            )
            self.uow.events.save(
                Event(
                    event_type=EventType.PROVIDER_HEALTH_UPDATED,
                    payload={
                        "provider": outcome.provider,
                        "status": target_status.value,
                        "consecutive_failures": new_failures,
                        "result_class": outcome.result_class.value,
                        "summary": outcome.summary,
                    },
                    timestamp=now,
                )
            )
            self.uow.commit()
            return new_health

    def _probe_config(self, provider: str) -> ProbeConfig:
        if provider in self.probe_configs:
            return self.probe_configs[provider]
        return self.probe_config or ProbeConfig()

    def _get_probe_lock(self, provider: str) -> asyncio.Lock:
        lock = self._probe_locks.get(provider)
        if lock is None:
            lock = asyncio.Lock()
            self._probe_locks[provider] = lock
        return lock

    def _probe_eligible(
        self,
        provider: str,
        health: ProviderHealth,
        baseline_at: datetime | None = None,
    ) -> bool:
        cfg = self._probe_config(provider)
        failures = max(0, health.consecutive_probe_failures)
        backoff = 0
        if failures >= 1:
            backoff = min(
                cfg.backoff_base_seconds * (2 ** (failures - 1)),
                cfg.backoff_max_seconds,
            )
        interval = max(cfg.cooldown_seconds, backoff)

        anchor = health.last_probe_at
        if anchor is None:
            # No prior probe: anchor first-probe eligibility to the exhaustion
            # baseline (the authoritative capacity window) so the first expensive
            # recovery probe still respects the configured cooldown rather than
            # firing immediately on unknown reset.
            anchor = baseline_at
            if anchor is None:
                return True
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=UTC)
        eligible_at = anchor + timedelta(seconds=interval)
        return utc_now() >= eligible_at

    def _record_probe_attempt(self, provider: str, succeeded: bool) -> None:
        health = self.get_health(provider)
        if succeeded:
            health.consecutive_probe_failures = 0
        else:
            health.consecutive_probe_failures = health.consecutive_probe_failures + 1
        health.last_probe_at = utc_now()
        self.uow.provider_health.save(health)
        self.uow.commit()

    def _try_reserve_expensive_probe(
        self,
        provider: str,
        cfg: ProbeConfig,
        baseline_at: datetime | None = None,
    ) -> bool:
        """Atomically evaluate and reserve an expensive-probe dispatch slot.

        Locks the provider's health row ``FOR UPDATE`` so competing PostgreSQL
        sessions serialize on the same physical row, then re-evaluates
        cooldown/backoff eligibility, the rolling one-hour window, and the
        per-window maximum against the freshly locked state. The reservation is
        committed in the same transaction as the lock, so the lock is released
        only after the reservation is durable and before the external probe is
        dispatched. Returns True only when this caller durably reserved the slot.
        """
        fresh = self.uow.provider_health.get_by_provider_for_update(provider)
        if fresh is None:
            # get_health above materialized the row; a missing row means we cannot
            # reserve. Release the (vacuous) lock and decline.
            self.uow.rollback()
            return False

        if not self._probe_eligible(provider, fresh, baseline_at=baseline_at):
            self.uow.rollback()
            return False

        now = utc_now()
        started = fresh.probe_window_started_at
        if started is not None and started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if started is None or (now - started) >= timedelta(seconds=3600):
            # Roll the fixed one-hour window in place; no intermediate commit so
            # the FOR UPDATE lock is held across the entire evaluation+reservation.
            fresh.probe_window_started_at = now
            fresh.probe_count_in_window = 0

        if fresh.probe_count_in_window >= cfg.max_per_hour:
            # Bound suppression evidence: at most one suppression event per
            # provider per hour, regardless of scheduler tick count.
            if not self._suppression_already_recorded(provider):
                self.uow.events.save(
                    Event(
                        event_type=EventType.PROVIDER_PROBE_SUPPRESSED,
                        payload={
                            "provider": provider,
                            "kind": "expensive",
                            "reason": "MAX_PER_HOUR",
                        },
                        timestamp=now,
                    )
                )
                self.uow.commit()
            else:
                self.uow.rollback()
            return False

        # Reserve the dispatch slot AND mark the dispatch time durably so queued
        # callers (in-process and cross-session) observe an updated last_probe_at
        # and probe_count_in_window and fail the cooldown/backoff or max-per-hour
        # check rather than dispatching additional expensive probes.
        fresh.probe_count_in_window += 1
        fresh.last_probe_at = now
        self.uow.provider_health.save(fresh)
        self.uow.commit()
        return True

    def _suppression_already_recorded(self, provider: str) -> bool:
        cutoff = utc_now() - timedelta(seconds=3600)
        return (
            self.uow.events.count_events(
                event_type=EventType.PROVIDER_PROBE_SUPPRESSED.value,
                provider=provider,
                since=cutoff,
            )
            > 0
        )

    async def check_and_probe_provider(
        self,
        provider: str,
        probe_fn: Callable[[], Coroutine[Any, Any, bool]] | None = None,
    ) -> bool:
        """Check provider availability; if reset timestamp has elapsed, execute probe before restoring available."""
        self._validate_primary(provider)
        health = self.get_health(provider)

        if health.status == ProviderHealthStatus.AVAILABLE:
            return True

        # Known future reset: never probe before the reset window.
        latest_window = self.uow.capacity_windows.get_latest_for_provider(provider)
        if latest_window and latest_window.capacity_reset_at:
            reset_at = latest_window.capacity_reset_at
            if reset_at.tzinfo is None:
                reset_at = reset_at.replace(tzinfo=UTC)
            if reset_at > utc_now():
                return False

        managed_probe = probe_fn is None
        expensive = False
        verifies_capacity = True  # injected probe_fn: caller's probe is authoritative

        if managed_probe:
            adapter = get_provider_adapter(provider)

            # Readiness gate: never dispatch an inference-capable capacity probe when
            # local CLI presence or authentication readiness is known to have failed.
            if not await adapter.check_cli_present():
                self.uow.provider_health.update_health(
                    provider=provider,
                    status=ProviderHealthStatus.MISCONFIGURED.value,
                    result_class=ProviderResultClass.UNKNOWN_ERROR.value,
                    error_summary=(
                        "Provider CLI executable is not present; readiness failed without inference"
                    ),
                )
                self.uow.events.save(
                    Event(
                        event_type=EventType.PROVIDER_HEALTH_UPDATED,
                        payload={
                            "provider": provider,
                            "status": ProviderHealthStatus.MISCONFIGURED.value,
                            "reason": "CLI_NOT_PRESENT",
                        },
                        timestamp=utc_now(),
                    )
                )
                self.uow.commit()
                return False

            if not await adapter.check_auth_ready():
                self.uow.provider_health.update_health(
                    provider=provider,
                    status=ProviderHealthStatus.AUTH_REQUIRED.value,
                    result_class=ProviderResultClass.AUTH_ERROR.value,
                    error_summary=(
                        "Provider authentication is unavailable; readiness failed without inference"
                    ),
                )
                self.uow.events.save(
                    Event(
                        event_type=EventType.PROVIDER_HEALTH_UPDATED,
                        payload={
                            "provider": provider,
                            "status": ProviderHealthStatus.AUTH_REQUIRED.value,
                            "reason": "AUTH_NOT_READY",
                        },
                        timestamp=utc_now(),
                    )
                )
                self.uow.commit()
                return False

            expensive = bool(adapter.probe_is_expensive)
            verifies_capacity = bool(adapter.probe_verifies_capacity)

            if expensive:
                cfg = self._probe_config(provider)
                async with self._get_probe_lock(provider):
                    # The in-process lock serializes callers within this instance.
                    # The FOR UPDATE row lock inside _try_reserve_expensive_probe is
                    # the canonical cross-session boundary: it also serializes other
                    # SchedulerService / ProviderHealthService instances sharing
                    # PostgreSQL, so a stale shared read can never reserve twice.
                    if not self._try_reserve_expensive_probe(
                        provider,
                        cfg,
                        baseline_at=(
                            latest_window.quota_exhausted_at if latest_window else None
                        ),
                    ):
                        return False
            else:
                if not self._probe_eligible(
                    provider,
                    health,
                    baseline_at=(
                        latest_window.quota_exhausted_at if latest_window else None
                    ),
                ):
                    return False

            async def _default_probe() -> bool:
                return await adapter.probe_availability(timeout_seconds=30.0)

            probe_fn = _default_probe

        logger.info(
            f"Provider {provider} reset window elapsed or probe eligible. Executing availability probe."
        )
        try:
            probe_success = await asyncio.wait_for(probe_fn(), timeout=30.0)
        except Exception as e:
            logger.warning(f"Availability probe for {provider} raised exception or timed out: {e}")
            probe_success = False

        if managed_probe:
            self._record_probe_attempt(provider, succeeded=probe_success)
            if expensive:
                self.uow.events.save(
                    Event(
                        event_type=EventType.PROVIDER_PROBE_EXECUTED,
                        payload={
                            "provider": provider,
                            "kind": "expensive",
                            "result": "success" if probe_success else "failure",
                            "expensive": True,
                        },
                        timestamp=utc_now(),
                    )
                )
                self.uow.commit()

        if probe_success and verifies_capacity:
            logger.info(
                f"Availability probe for {provider} SUCCEEDED. Transitioning to AVAILABLE."
            )
            self.uow.provider_health.update_health(
                provider=provider,
                status=ProviderHealthStatus.AVAILABLE.value,
                result_class=ProviderResultClass.SUCCESS.value,
                error_summary="Recovered via successful capacity reset probe",
                consecutive_failures=0,
            )
            self.uow.events.save(
                Event(
                    event_type=EventType.PRIMARY_CAPACITY_RECOVERED,
                    payload={
                        "provider": provider,
                        "probe_verified": True,
                        "status": ProviderHealthStatus.AVAILABLE.value,
                    },
                    timestamp=utc_now(),
                )
            )
            self.uow.commit()
            return True
        elif probe_success:
            # Readiness/reachability probe succeeded but does NOT verify inference
            # capacity recovery (e.g. Antigravity `agy models`). Preserve UNKNOWN
            # capacity: never promote an exhausted provider on a non-inference signal.
            logger.info(
                f"Readiness probe for {provider} succeeded but does not verify capacity; "
                "provider remains in its current non-available state."
            )
            self.uow.events.save(
                Event(
                    event_type=EventType.PROVIDER_HEALTH_UPDATED,
                    payload={
                        "provider": provider,
                        "status": health.status.value,
                        "reason": "READINESS_CONFIRMED_CAPACITY_UNKNOWN",
                    },
                    timestamp=utc_now(),
                )
            )
            self.uow.commit()
            return False
        else:
            logger.warning(
                f"Availability probe for {provider} FAILED. Provider remains unavailable."
            )
            self.uow.events.save(
                Event(
                    event_type=EventType.PROVIDER_PROBE_FAILED,
                    payload={
                        "provider": provider,
                        "probe_verified": False,
                        "status": health.status.value,
                    },
                    timestamp=utc_now(),
                )
            )
            self.uow.commit()
            return False

    async def probe_unavailable_providers(self) -> list[str]:
        """Proactively probe all currently unavailable providers in background without creating Runs/Jobs."""
        all_health = self.list_all_health()
        recovered: list[str] = []
        for h in all_health:
            if h.status != ProviderHealthStatus.AVAILABLE:
                success = await self.check_and_probe_provider(h.provider)
                if success:
                    recovered.append(h.provider)
        return recovered

    def is_pair_available(self, implementer: str, reviewer: str) -> tuple[bool, str | None]:
        """Verify that both primary roles in the complementary pair are currently AVAILABLE."""
        self._validate_primary(implementer)
        self._validate_primary(reviewer)

        imp_health = self.get_health(implementer)
        rev_health = self.get_health(reviewer)

        if imp_health.status != ProviderHealthStatus.AVAILABLE:
            return False, f"Primary implementer '{implementer}' is {imp_health.status.value}"
        if rev_health.status != ProviderHealthStatus.AVAILABLE:
            return False, f"Primary reviewer '{reviewer}' is {rev_health.status.value}"

        return True, None
