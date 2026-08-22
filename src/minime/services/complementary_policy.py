"""Complementary reviewer policy validation."""

from __future__ import annotations


def validate_complementary_pair(implementer: str, reviewer: str) -> tuple[bool, str | None]:
    """Validate that the implementer and reviewer conform to complementary primary pairing."""
    imp = implementer.strip().lower()
    rev = reviewer.strip().lower()

    if not imp or not rev:
        return False, "Implementer and reviewer roles must both be specified."

    if imp == rev:
        return (
            False,
            f"Self-review is prohibited: implementer and reviewer cannot both be '{implementer}'.",
        )

    valid_pairs = {
        "codex": "antigravity",
        "antigravity": "codex",
    }

    if imp not in valid_pairs:
        return (
            False,
            f"Unsupported implementer '{implementer}'. Must be 'codex' or 'antigravity'.",
        )

    expected_reviewer = valid_pairs[imp]
    if rev != expected_reviewer:
        return (
            False,
            f"Invalid complementary pairing: implementer '{implementer}' requires reviewer '{expected_reviewer}', but got '{reviewer}'.",
        )

    return True, None
