"""Strict, unambiguous parser and validator for machine-readable reviewer verdicts."""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from minime.domain.enums import FindingSeverity, ReviewVerdict
from minime.domain.models import ReviewVerdictPayload


class MalformedReviewOutputError(ValueError):
    """Raised when reviewer output cannot be unambiguously parsed into an authoritative verdict."""

    pass


def parse_review_verdict(raw_output: str | list[str]) -> ReviewVerdictPayload:
    """Extract and validate exactly one unambiguous ReviewVerdictPayload from reviewer output.

    Rejects missing, duplicate, conflicting, partially valid, or ambiguous payloads.
    Never defaults to READY_TO_MERGE.
    """
    if isinstance(raw_output, list):
        text = "\n".join(raw_output).strip()
    else:
        text = str(raw_output).strip()

    if not text:
        raise MalformedReviewOutputError("Reviewer output is empty.")

    # 1. Look for fenced JSON codeblocks first
    fence_pattern = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)
    fenced_blocks = [b.strip() for b in fence_pattern.findall(text) if b.strip()]

    candidate_strings: list[str] = []
    if fenced_blocks:
        candidate_strings = fenced_blocks
    else:
        # 2. Look for top-level JSON objects containing "verdict"
        # Match outermost { ... }
        brace_pattern = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)
        candidate_strings = [m.group(0).strip() for m in brace_pattern.finditer(text)]

    if not candidate_strings:
        raise MalformedReviewOutputError("No structured JSON payload found in reviewer output.")

    valid_payloads: list[ReviewVerdictPayload] = []
    malformed_verdict_attempts: list[str] = []

    for candidate in candidate_strings:
        # Check if candidate mentions "verdict" or looks like a review payload
        if "verdict" not in candidate and "findings" not in candidate:
            continue

        try:
            data = json.loads(candidate)
            if not isinstance(data, dict) or "verdict" not in data:
                malformed_verdict_attempts.append(candidate)
                continue

            # Validate schema strictly
            payload = ReviewVerdictPayload.model_validate(data)

            # Validate finding fields
            for finding in payload.findings:
                if not finding.violated_requirement or not finding.violated_requirement.strip():
                    raise MalformedReviewOutputError(
                        "Finding missing required violated_requirement."
                    )
                if not finding.expected_correction or not finding.expected_correction.strip():
                    raise MalformedReviewOutputError(
                        "Finding missing required expected_correction."
                    )
                if finding.severity not in {
                    FindingSeverity.BLOCKER,
                    FindingSeverity.MAJOR,
                    FindingSeverity.MINOR,
                }:
                    raise MalformedReviewOutputError(
                        f"Finding has unsupported severity: {finding.severity}"
                    )

            # Validate logical consistency
            if payload.verdict == ReviewVerdict.READY_TO_MERGE:
                if payload.findings:
                    raise MalformedReviewOutputError(
                        "Inconsistent reviewer payload: verdict is READY_TO_MERGE but non-empty findings were returned."
                    )
            elif payload.verdict == ReviewVerdict.CHANGES_REQUIRED:
                if not payload.findings:
                    raise MalformedReviewOutputError(
                        "Inconsistent reviewer payload: verdict is CHANGES_REQUIRED but no findings were returned."
                    )
            else:
                raise MalformedReviewOutputError(f"Unsupported review verdict: {payload.verdict}")

            valid_payloads.append(payload)

        except (json.JSONDecodeError, ValidationError, MalformedReviewOutputError) as exc:
            malformed_verdict_attempts.append(f"{candidate} (Error: {exc})")

    # Ambiguity checks
    if len(valid_payloads) == 0:
        if malformed_verdict_attempts:
            raise MalformedReviewOutputError(
                f"Failed to parse valid structured review verdict: {malformed_verdict_attempts[0]}"
            )
        raise MalformedReviewOutputError("No structured verdict payload found in reviewer output.")

    if len(valid_payloads) > 1:
        raise MalformedReviewOutputError(
            f"Ambiguous reviewer output: found {len(valid_payloads)} structured verdict payloads."
        )

    if malformed_verdict_attempts:
        raise MalformedReviewOutputError(
            f"Ambiguous reviewer output: found valid payload alongside malformed payload attempts: {malformed_verdict_attempts[0]}"
        )

    return valid_payloads[0]
