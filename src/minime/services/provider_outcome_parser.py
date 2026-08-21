"""Provider outcome normalizer and error classification conforming to schemas/provider-result.schema.json."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from minime.domain.enums import (
    ProviderResultClass,
)
from minime.domain.models import NormalizedProviderResult, utc_now


class ProviderOutcomeParser:
    """Classifies raw execution/CLI/HTTP outputs into normalized result classes."""

    # Patterns for quota exhaustion
    _QUOTA_PATTERNS = [
        re.compile(r"insufficient_quota", re.IGNORECASE),
        re.compile(r"quota[_\s-]?limit", re.IGNORECASE),
        re.compile(r"quota[_\s-]?exceeded", re.IGNORECASE),
        re.compile(r"exceeded\s+your\s+current\s+quota", re.IGNORECASE),
        re.compile(r"capacity\s+exhausted", re.IGNORECASE),
        re.compile(r"resource_exhausted", re.IGNORECASE),
        re.compile(r"out\s+of\s+credits", re.IGNORECASE),
        re.compile(r"monthly\s+limit\s+reached", re.IGNORECASE),
    ]

    # Patterns for rate limits
    _RATE_LIMIT_PATTERNS = [
        re.compile(r"rate_limit_exceeded", re.IGNORECASE),
        re.compile(r"rate[_\s-]?limit", re.IGNORECASE),
        re.compile(r"too\s+many\s+requests", re.IGNORECASE),
        re.compile(r"http\s+429", re.IGNORECASE),
        re.compile(r"status\s+429", re.IGNORECASE),
        re.compile(r"requests\s+per\s+minute", re.IGNORECASE),
        re.compile(r"tokens\s+per\s+minute", re.IGNORECASE),
    ]

    # Patterns for auth errors
    _AUTH_PATTERNS = [
        re.compile(r"invalid_api_key", re.IGNORECASE),
        re.compile(r"authentication_failed", re.IGNORECASE),
        re.compile(r"unauthorized", re.IGNORECASE),
        re.compile(r"http\s+401", re.IGNORECASE),
        re.compile(r"status\s+401", re.IGNORECASE),
        re.compile(r"http\s+403", re.IGNORECASE),
        re.compile(r"status\s+403", re.IGNORECASE),
        re.compile(r"forbidden", re.IGNORECASE),
    ]

    # Patterns for transient errors
    _TRANSIENT_PATTERNS = [
        re.compile(r"connection\s+reset", re.IGNORECASE),
        re.compile(r"connection\s+refused", re.IGNORECASE),
        re.compile(r"econnrefused", re.IGNORECASE),
        re.compile(r"econnreset", re.IGNORECASE),
        re.compile(r"temporary\s+failure", re.IGNORECASE),
        re.compile(r"service\s+unavailable", re.IGNORECASE),
        re.compile(r"http\s+503", re.IGNORECASE),
        re.compile(r"http\s+502", re.IGNORECASE),
        re.compile(r"bad\s+gateway", re.IGNORECASE),
        re.compile(r"gateway\s+timeout", re.IGNORECASE),
        re.compile(r"http\s+504", re.IGNORECASE),
        re.compile(r"network\s+unreachable", re.IGNORECASE),
        re.compile(r"dns\s+resolution\s+failed", re.IGNORECASE),
    ]

    # Patterns for reset/retry timestamp or seconds
    _RETRY_AFTER_HEADER_PATTERN = re.compile(r"retry-after:\s*([0-9]+)", re.IGNORECASE)
    _RESET_TIMESTAMP_PATTERN = re.compile(
        r"(?:reset(?:_at)?|resets?\s+at)\s*[:=]?\s*([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2}))",
        re.IGNORECASE,
    )
    _RETRY_SECONDS_PATTERN = re.compile(
        r"(?:try\s+again\s+in|retry\s+after)\s*([0-9]+)\s*(?:s|sec|seconds?)",
        re.IGNORECASE,
    )

    @classmethod
    def parse_runner_output(
        cls,
        provider: str,
        role: str,
        model: str | None,
        exit_code: int,
        timed_out: bool,
        stdout_lines: list[str],
        stderr_lines: list[str],
        domain_verdict_valid: bool = False,
    ) -> NormalizedProviderResult:
        """Parse raw process runner output into a NormalizedProviderResult."""
        combined_text = "\n".join(stdout_lines + stderr_lines)

        # 1. If timeout occurred
        if timed_out:
            return NormalizedProviderResult(
                result_class=ProviderResultClass.TIMEOUT,
                provider=provider,
                role=role,
                model=model,
                summary=f"Provider {provider} timed out during {role} execution",
                raw_output=combined_text[:1000],
            )

        # 2. Domain verdict validity check: If valid domain verdict is recognized (e.g. CHANGES_REQUIRED or READY_TO_MERGE)
        # Domain verdicts represent valid outcomes and do not degrade provider health.
        if domain_verdict_valid:
            return NormalizedProviderResult(
                result_class=ProviderResultClass.SUCCESS,
                provider=provider,
                role=role,
                model=model,
                summary=f"Provider {provider} completed successfully for {role}",
                raw_output=combined_text[:1000],
            )

        # 3. Clean exit with 0 code
        if exit_code == 0:
            return NormalizedProviderResult(
                result_class=ProviderResultClass.SUCCESS,
                provider=provider,
                role=role,
                model=model,
                summary=f"Provider {provider} exited successfully",
                raw_output=combined_text[:1000],
            )

        # 4. Check for quota exhaustion
        for pat in cls._QUOTA_PATTERNS:
            if pat.search(combined_text):
                retry_after, reset_at = cls.extract_reset_hints(combined_text)
                return NormalizedProviderResult(
                    result_class=ProviderResultClass.QUOTA_LIMIT,
                    provider=provider,
                    role=role,
                    model=model,
                    retry_after=retry_after,
                    capacity_reset_at=reset_at,
                    summary=f"Quota exhausted for provider {provider}",
                    raw_output=combined_text[:1000],
                )

        # 5. Check for rate limit
        for pat in cls._RATE_LIMIT_PATTERNS:
            if pat.search(combined_text):
                retry_after, reset_at = cls.extract_reset_hints(combined_text)
                return NormalizedProviderResult(
                    result_class=ProviderResultClass.RATE_LIMIT,
                    provider=provider,
                    role=role,
                    model=model,
                    retry_after=retry_after,
                    capacity_reset_at=reset_at,
                    summary=f"Rate limit exceeded for provider {provider}",
                    raw_output=combined_text[:1000],
                )

        # 6. Check for auth error
        for pat in cls._AUTH_PATTERNS:
            if pat.search(combined_text):
                return NormalizedProviderResult(
                    result_class=ProviderResultClass.AUTH_ERROR,
                    provider=provider,
                    role=role,
                    model=model,
                    summary=f"Authentication error for provider {provider}",
                    raw_output=combined_text[:1000],
                )

        # 7. Check for transient error
        for pat in cls._TRANSIENT_PATTERNS:
            if pat.search(combined_text):
                return NormalizedProviderResult(
                    result_class=ProviderResultClass.TRANSIENT_ERROR,
                    provider=provider,
                    role=role,
                    model=model,
                    summary=f"Transient network or infrastructure error for provider {provider}",
                    raw_output=combined_text[:1000],
                )

        # 8. Check for malformed output
        if "jsondecodeerror" in combined_text.lower() or "malformed" in combined_text.lower():
            return NormalizedProviderResult(
                result_class=ProviderResultClass.MALFORMED_OUTPUT,
                provider=provider,
                role=role,
                model=model,
                summary=f"Malformed output received from provider {provider}",
                raw_output=combined_text[:1000],
            )

        # 9. Fallback: unknown error
        return NormalizedProviderResult(
            result_class=ProviderResultClass.UNKNOWN_ERROR,
            provider=provider,
            role=role,
            model=model,
            summary=f"Provider {provider} failed with exit code {exit_code}",
            raw_output=combined_text[:1000],
        )

    @classmethod
    def extract_reset_hints(cls, text: str) -> tuple[str | None, datetime | None]:
        """Extract retry_after (seconds as string) and capacity_reset_at from error text."""
        retry_after: str | None = None
        reset_at: datetime | None = None

        # Check for header-style retry-after
        m_header = cls._RETRY_AFTER_HEADER_PATTERN.search(text)
        if m_header:
            retry_after = m_header.group(1)
            try:
                seconds = int(retry_after)
                reset_at = utc_now() + timedelta(seconds=seconds)
            except ValueError:
                pass

        # Check for try again in X seconds
        if not retry_after:
            m_sec = cls._RETRY_SECONDS_PATTERN.search(text)
            if m_sec:
                retry_after = m_sec.group(1)
                try:
                    seconds = int(retry_after)
                    reset_at = utc_now() + timedelta(seconds=seconds)
                except ValueError:
                    pass

        # Check for ISO timestamp
        m_ts = cls._RESET_TIMESTAMP_PATTERN.search(text)
        if m_ts:
            ts_str = m_ts.group(1)
            try:
                if ts_str.endswith("Z"):
                    ts_str = ts_str[:-1] + "+00:00"
                parsed_dt = datetime.fromisoformat(ts_str)
                if parsed_dt.tzinfo is None:
                    parsed_dt = parsed_dt.replace(tzinfo=UTC)
                reset_at = parsed_dt
            except ValueError:
                pass

        return retry_after, reset_at
