from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from minime.adapters.provider_adapter import get_provider_adapter
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
    ):
        self.uow = uow
        self.failure_threshold = failure_threshold

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

        # If exhausted or temporarily unavailable, check if reset window has elapsed
        latest_window = self.uow.capacity_windows.get_latest_for_provider(provider)
        now = utc_now()
        is_reset_elapsed = False

        if latest_window and latest_window.capacity_reset_at:
            reset_at = latest_window.capacity_reset_at
            if reset_at.tzinfo is None:
                reset_at = reset_at.replace(tzinfo=UTC)
            is_reset_elapsed = reset_at <= now
        else:
            # Unknown reset timing must not permanently prevent probing
            is_reset_elapsed = True

        if not is_reset_elapsed:
            return False

        if probe_fn is None:
            adapter = get_provider_adapter(provider)

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

        if probe_success:
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
