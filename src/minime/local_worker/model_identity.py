"""Canonical local worker provider/model identity for the minimal local worker bootstrap.

The local worker capability executes bounded LOW-risk coding work through a single local
Ollama model whose identity is exact and self-describing. The same provider/model must never
be granted review, audit or merge authority for a candidate it substantively produced.
"""

from __future__ import annotations

OLLAMA_PROVIDER = "ollama"

# Implement-oriented role only. Local Qwen provider never claims reviewer/auditor roles.
LOCAL_WORKER_ROLE = "local_worker"

# Exact canonical model identity for the minimal local worker bootstrap.
QWEN2_5_CODER_7B_INSTRUCT_Q4_K_M = "qwen2.5-coder:7b-instruct-q4_K_M"

# Authorities local Qwen is explicitly forbidden from exercising.
LOCAL_QWEN_FORBIDDEN_AUTHORITIES = frozenset(
    {"review", "audit", "merge", "approve", "validate_self_success"}
)


def local_qwen_model_identity() -> str:
    """Return the single canonical model identity for the local worker."""
    return QWEN2_5_CODER_7B_INSTRUCT_Q4_K_M


def is_canonical_local_qwen_model(model: str) -> bool:
    """Return True only when ``model`` exactly matches the canonical identity."""
    return model == QWEN2_5_CODER_7B_INSTRUCT_Q4_K_M


def assert_local_qwen_model(model: str, *, field: str = "model") -> None:
    """Raise ValueError when ``model`` is not the exact canonical local Qwen identity."""
    if not is_canonical_local_qwen_model(model):
        raise ValueError(
            f"{field} must be the exact canonical local Qwen model "
            f"'{QWEN2_5_CODER_7B_INSTRUCT_Q4_K_M}', got '{model}'"
        )
