"""Unit tests for canonical model identity normalization, fail-closed verification, and model independence policy."""

from minime.services.model_identity_service import CanonicalModelRegistry
from minime.services.model_independence_policy import ModelIndependencePolicy


def test_exact_known_model_resolves():
    registry = CanonicalModelRegistry()
    m = registry.normalize("anthropic/claude-3.5-sonnet")
    assert m is not None
    assert m.canonical_name == "anthropic:claude-3.5-sonnet"
    assert m.family == "anthropic"


def test_aliases_normalize_to_same_canonical_identity():
    registry = CanonicalModelRegistry()
    a = registry.normalize("qwen/qwen3-coder")
    b = registry.normalize("qwen/qwen3-coder-plus")
    assert a is not None and b is not None
    assert a.canonical_name == b.canonical_name
    assert a.family == "qwen"

    c = registry.normalize("anthropic/claude-3.5-sonnet")
    d = registry.normalize("anthropic/claude-3.5-sonnet:beta")
    assert c is not None and d is not None
    assert c.canonical_name == d.canonical_name
    assert c.family == "anthropic"


def test_same_family_self_review_rejected():
    policy = ModelIndependencePolicy()
    # Qwen 3 coder vs Qwen 2.5 coder (same family 'qwen') -> REJECTED
    ok, reason = policy.validate("qwen/qwen3-coder", "qwen/qwen-2.5-coder-32b-instruct")
    assert ok is False
    assert reason == "DISTINCT_REVIEWER_UNAVAILABLE"


def test_exact_same_model_rejected():
    policy = ModelIndependencePolicy()
    ok, reason = policy.validate("anthropic/claude-3.5-sonnet", "anthropic/claude-3.5-sonnet")
    assert ok is False
    assert reason == "DISTINCT_REVIEWER_UNAVAILABLE"


def test_unknown_provider_model_denied_fail_closed():
    registry = CanonicalModelRegistry()
    # Arbitrary unapproved model strings must return None (fail closed)
    assert registry.normalize("unknown-provider/some-model") is None
    assert registry.normalize("untrusted-corp/magic-model-70b") is None


def test_malformed_model_string_denied():
    registry = CanonicalModelRegistry()
    assert registry.normalize("") is None
    assert registry.normalize("   ") is None
    assert registry.normalize(None) is None
    assert registry.normalize("/missing-provider") is None
    assert registry.normalize("provider/") is None
    assert registry.normalize("provider/model/extra/slashes") is None
    assert registry.normalize(":::") is None


def test_syntactically_valid_but_unregistered_model_denied():
    registry = CanonicalModelRegistry()
    # Looks like valid provider/model but not in pinned trusted registry -> FAIL CLOSED
    assert registry.normalize("anthropic/claude-future-99") is None
    assert registry.normalize("openai/gpt-9-omni") is None
    assert registry.normalize("meta-llama/llama-9-999b") is None


def test_unprovable_identity_fails_closed():
    policy = ModelIndependencePolicy()
    ok, reason = policy.validate("", "anthropic/claude-3.5-sonnet")
    assert ok is False
    assert reason == "DISTINCT_REVIEWER_UNAVAILABLE"

    ok, reason = policy.validate(None, "openai/gpt-4o")
    assert ok is False
    assert reason == "DISTINCT_REVIEWER_UNAVAILABLE"

    # One model valid, other unprovable -> FAIL CLOSED
    ok, reason = policy.validate("anthropic/claude-3.5-sonnet", "untrusted/unknown-model")
    assert ok is False
    assert reason == "DISTINCT_REVIEWER_UNAVAILABLE"


def test_distinct_models_allowed_when_both_proven():
    policy = ModelIndependencePolicy()
    ok, reason = policy.validate("anthropic/claude-3.5-sonnet", "openai/gpt-4o")
    assert ok is True
    assert reason is None

    ok2, reason2 = policy.validate("qwen/qwen-2.5-coder-32b-instruct", "meta-llama/llama-3.3-70b-instruct")
    assert ok2 is True
    assert reason2 is None


def test_select_independent_reviewer():
    policy = ModelIndependencePolicy()
    allowed = [
        "qwen/qwen-2.5-72b-instruct",  # same family as qwen3-coder -> should be skipped
        "qwen/qwen3-coder-plus",        # same model alias -> should be skipped
        "openai/gpt-4o",                # distinct -> should be selected
        "meta-llama/llama-3.3-70b-instruct",
    ]
    selected, identity = policy.select_independent_reviewer("qwen/qwen3-coder", allowed)
    assert selected == "openai/gpt-4o"
    assert identity is not None
    assert identity.canonical_name == "openai:gpt-4o"


def test_select_independent_reviewer_none_available():
    policy = ModelIndependencePolicy()
    allowed = [
        "qwen/qwen-2.5-72b-instruct",
        "qwen/qwen-2.5-coder-32b",
    ]
    selected, identity = policy.select_independent_reviewer("qwen/qwen3-coder", allowed)
    assert selected is None
    assert identity is None
