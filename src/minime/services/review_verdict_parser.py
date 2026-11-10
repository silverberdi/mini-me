"""Strict, unambiguous parser and validator for machine-readable reviewer verdicts."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from minime.domain.enums import FindingSeverity, ReviewVerdict
from minime.domain.models import ReviewVerdictPayload


class MalformedReviewOutputError(ValueError):
    """Raised when reviewer output cannot be unambiguously parsed into an authoritative verdict."""

    pass


def _extract_candidate_payloads(text: str) -> list[tuple[dict[str, Any] | None, str]]:
    """Extract candidate JSON objects from fenced codeblocks or raw stream using JSONDecoder."""
    decoder = json.JSONDecoder()
    fenced_candidates: list[tuple[dict[str, Any] | None, str]] = []

    # 1. Inspect fenced codeblocks first
    fence_pattern = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)
    fenced_blocks = [b.strip() for b in fence_pattern.findall(text) if b.strip()]
    for block in fenced_blocks:
        idx = block.find("{")
        if idx != -1:
            try:
                obj, _ = decoder.raw_decode(block[idx:])
                if isinstance(obj, dict) and ("verdict" in obj or "findings" in obj):
                    fenced_candidates.append((obj, block))
            except (json.JSONDecodeError, ValueError):
                if "verdict" in block or "findings" in block:
                    fenced_candidates.append((None, block))
        elif "verdict" in block or "findings" in block:
            fenced_candidates.append((None, block))

    # If any fenced block produced a verdict candidate, prefer fenced blocks
    if any(isinstance(c[0], dict) and "verdict" in c[0] for c in fenced_candidates):
        return fenced_candidates

    # 2. Otherwise (or if fenced blocks were only ancillary snippets like CSS),
    # scan text for top-level JSON objects using raw_decode
    raw_candidates: list[tuple[dict[str, Any] | None, str]] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "{":
            try:
                obj, end = decoder.raw_decode(text[i:])
                slice_text = text[i : i + end]
                if isinstance(obj, dict) and ("verdict" in obj or "findings" in obj):
                    raw_candidates.append((obj, slice_text))
                i += max(end, 1)
                continue
            except (json.JSONDecodeError, ValueError):
                pass
        i += 1

    if raw_candidates:
        return raw_candidates

    # Check if raw text had an unparseable verdict attempt
    broken_match = re.search(r'\{[^{}]*"(?:verdict|findings)"', text)
    if broken_match:
        start = broken_match.start()
        raw_candidates.append((None, text[start : start + 300]))
        return raw_candidates

    return fenced_candidates


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

    candidates = _extract_candidate_payloads(text)
    if not candidates:
        raise MalformedReviewOutputError("No structured JSON payload found in reviewer output.")

    valid_payloads: list[ReviewVerdictPayload] = []
    malformed_verdict_attempts: list[str] = []

    for candidate_obj, candidate_raw in candidates:
        if candidate_obj is None:
            malformed_verdict_attempts.append(candidate_raw)
            continue

        if not isinstance(candidate_obj, dict) or "verdict" not in candidate_obj:
            malformed_verdict_attempts.append(candidate_raw)
            continue

        try:
            payload = ReviewVerdictPayload.model_validate(candidate_obj)

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

        except (ValidationError, MalformedReviewOutputError) as exc:
            malformed_verdict_attempts.append(f"{candidate_raw} (Error: {exc})")

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
