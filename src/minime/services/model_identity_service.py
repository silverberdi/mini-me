"""Canonical model identity normalization for OpenRouter fallback with fail-closed verification."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalModelIdentity:
    provider: str
    family: str
    architecture: str
    canonical_name: str


class CanonicalModelRegistry:
    """Registry mapping OpenRouter model strings and routing aliases to canonical identities.

    Fails closed: Any model string, alias, or route that is not explicitly registered
    as trusted/proven is rejected (returns None). No heuristic guessing is permitted.
    """

    def __init__(self) -> None:
        self._pinned_models: dict[str, CanonicalModelIdentity] = {}
        self._initialize_canonical_registry()

    def _initialize_canonical_registry(self) -> None:
        # Pinned canonical identities for approved models & verified aliases
        # Qwen family
        qwen_coder_32b = CanonicalModelIdentity("openrouter", "qwen", "qwen-2.5-coder-32b", "qwen:qwen-2.5-coder-32b")
        qwen_coder_3 = CanonicalModelIdentity("openrouter", "qwen", "qwen3-coder", "qwen:qwen3-coder")
        qwen_72b = CanonicalModelIdentity("openrouter", "qwen", "qwen-2.5-72b", "qwen:qwen-2.5-72b")

        for alias in [
            "qwen/qwen-2.5-coder-32b-instruct",
            "qwen/qwen-2.5-coder-32b-instruct:free",
            "qwen/qwen-2.5-coder-32b-instruct:exact",
            "qwen/qwen-2.5-coder-32b-instruct:nitro",
            "qwen/qwen-2.5-coder-32b",
            "qwen:qwen-2.5-coder-32b",
        ]:
            self._pinned_models[alias.lower()] = qwen_coder_32b

        for alias in [
            "qwen/qwen3-coder",
            "qwen/qwen3-coder:free",
            "qwen/qwen3-coder-plus",
            "qwen:qwen3-coder",
        ]:
            self._pinned_models[alias.lower()] = qwen_coder_3

        for alias in [
            "qwen/qwen-2.5-72b-instruct",
            "qwen/qwen-2.5-72b-instruct:free",
            "qwen/qwen-2.5-72b",
            "qwen:qwen-2.5-72b",
        ]:
            self._pinned_models[alias.lower()] = qwen_72b

        # Anthropic family
        claude_35_sonnet = CanonicalModelIdentity("openrouter", "anthropic", "claude-3.5-sonnet", "anthropic:claude-3.5-sonnet")
        claude_35_haiku = CanonicalModelIdentity("openrouter", "anthropic", "claude-3.5-haiku", "anthropic:claude-3.5-haiku")
        claude_3_opus = CanonicalModelIdentity("openrouter", "anthropic", "claude-3-opus", "anthropic:claude-3-opus")

        for alias in [
            "anthropic/claude-3.5-sonnet",
            "anthropic/claude-3.5-sonnet:beta",
            "anthropic/claude-3.5-sonnet-20241022",
            "anthropic/claude-3-5-sonnet",
            "anthropic:claude-3.5-sonnet",
        ]:
            self._pinned_models[alias.lower()] = claude_35_sonnet

        for alias in [
            "anthropic/claude-3.5-haiku",
            "anthropic/claude-3.5-haiku:beta",
            "anthropic/claude-3-5-haiku",
            "anthropic:claude-3.5-haiku",
        ]:
            self._pinned_models[alias.lower()] = claude_35_haiku

        for alias in [
            "anthropic/claude-3-opus",
            "anthropic/claude-3-opus:beta",
            "anthropic:claude-3-opus",
        ]:
            self._pinned_models[alias.lower()] = claude_3_opus

        # OpenAI family
        gpt_4o = CanonicalModelIdentity("openrouter", "openai", "gpt-4o", "openai:gpt-4o")
        gpt_4o_mini = CanonicalModelIdentity("openrouter", "openai", "gpt-4o-mini", "openai:gpt-4o-mini")
        o1 = CanonicalModelIdentity("openrouter", "openai", "o1", "openai:o1")
        o1_mini = CanonicalModelIdentity("openrouter", "openai", "o1-mini", "openai:o1-mini")

        for alias in [
            "openai/gpt-4o",
            "openai/gpt-4o:extended",
            "openai/gpt-4o-2024-08-06",
            "openai/gpt-4o-2024-11-20",
            "openai:gpt-4o",
        ]:
            self._pinned_models[alias.lower()] = gpt_4o

        for alias in [
            "openai/gpt-4o-mini",
            "openai/gpt-4o-mini-2024-07-18",
            "openai:gpt-4o-mini",
        ]:
            self._pinned_models[alias.lower()] = gpt_4o_mini

        for alias in [
            "openai/o1",
            "openai/o1-preview",
            "openai:o1",
        ]:
            self._pinned_models[alias.lower()] = o1

        for alias in [
            "openai/o1-mini",
            "openai:o1-mini",
        ]:
            self._pinned_models[alias.lower()] = o1_mini

        # Meta Llama family
        llama_70b = CanonicalModelIdentity("openrouter", "llama", "llama-3.3-70b", "meta-llama:llama-3.3-70b")
        llama_70b_31 = CanonicalModelIdentity("openrouter", "llama", "llama-3.1-70b", "meta-llama:llama-3.1-70b")
        llama_405b = CanonicalModelIdentity("openrouter", "llama", "llama-3.1-405b", "meta-llama:llama-3.1-405b")

        for alias in [
            "meta-llama/llama-3.3-70b-instruct",
            "meta-llama/llama-3.3-70b-instruct:free",
            "meta-llama/llama-3.3-70b",
            "meta-llama:llama-3.3-70b",
        ]:
            self._pinned_models[alias.lower()] = llama_70b

        for alias in [
            "meta-llama/llama-3.1-70b-instruct",
            "meta-llama/llama-3.1-70b-instruct:free",
            "meta-llama/llama-3.1-70b",
            "meta-llama:llama-3.1-70b",
        ]:
            self._pinned_models[alias.lower()] = llama_70b_31

        for alias in [
            "meta-llama/llama-3.1-405b-instruct",
            "meta-llama/llama-3.1-405b",
            "meta-llama:llama-3.1-405b",
        ]:
            self._pinned_models[alias.lower()] = llama_405b

        # Mistral family
        mistral_large = CanonicalModelIdentity("openrouter", "mistral", "mistral-large", "mistralai:mistral-large")
        codestral = CanonicalModelIdentity("openrouter", "mistral", "codestral", "mistralai:codestral")

        for alias in [
            "mistralai/mistral-large",
            "mistralai/mistral-large-2411",
            "mistralai:mistral-large",
        ]:
            self._pinned_models[alias.lower()] = mistral_large

        for alias in [
            "mistralai/codestral-2501",
            "mistralai/codestral",
            "mistralai:codestral",
        ]:
            self._pinned_models[alias.lower()] = codestral

        # DeepSeek family
        deepseek_chat = CanonicalModelIdentity("openrouter", "deepseek", "deepseek-chat", "deepseek:deepseek-chat")
        deepseek_coder = CanonicalModelIdentity("openrouter", "deepseek", "deepseek-coder", "deepseek:deepseek-coder")

        for alias in [
            "deepseek/deepseek-chat",
            "deepseek/deepseek-chat:free",
            "deepseek:deepseek-chat",
        ]:
            self._pinned_models[alias.lower()] = deepseek_chat

        for alias in [
            "deepseek/deepseek-coder",
            "deepseek/deepseek-coder:free",
            "deepseek:deepseek-coder",
        ]:
            self._pinned_models[alias.lower()] = deepseek_coder

        # Google Gemini family
        gemini_pro = CanonicalModelIdentity("openrouter", "google", "gemini-1.5-pro", "google:gemini-1.5-pro")
        gemini_flash = CanonicalModelIdentity("openrouter", "google", "gemini-1.5-flash", "google:gemini-1.5-flash")

        for alias in [
            "google/gemini-pro-1.5",
            "google/gemini-1.5-pro",
            "google:gemini-1.5-pro",
        ]:
            self._pinned_models[alias.lower()] = gemini_pro

        for alias in [
            "google/gemini-flash-1.5",
            "google/gemini-1.5-flash",
            "google:gemini-1.5-flash",
        ]:
            self._pinned_models[alias.lower()] = gemini_flash

        # Primary provider names
        self._pinned_models["codex"] = CanonicalModelIdentity(
            "primary", "openai", "codex", "codex:primary"
        )
        self._pinned_models["antigravity"] = CanonicalModelIdentity(
            "primary", "google", "antigravity", "antigravity:primary"
        )

    def register_canonical_model(self, model_string: str, identity: CanonicalModelIdentity) -> None:
        """Explicitly register a trusted, verified canonical model identity."""
        if model_string and isinstance(model_string, str):
            self._pinned_models[model_string.strip().lower()] = identity

    def normalize(self, model_name: str | None) -> CanonicalModelIdentity | None:
        """Normalize a model name or route string into a canonical identity.

        Fails closed: If model is not explicitly registered in trusted known models,
        returns None. Never guesses or synthesizes untrusted identities.
        """
        if not model_name or not isinstance(model_name, str):
            return None
        key = model_name.strip().lower()
        if not key:
            return None

        # Check explicit pinned registry
        if key in self._pinned_models:
            return self._pinned_models[key]

        # Strip standard routing suffixes (:free, :beta, :nitro, :exact, :extended) if known base is present
        if ":" in key:
            base_key = key.split(":")[0]
            if base_key in self._pinned_models:
                return self._pinned_models[base_key]

        # FAIL CLOSED: Do not guess or invent canonical identities for arbitrary strings
        return None

    def is_independent(
        self, implementer: str | None, reviewer: str | None
    ) -> tuple[bool, str | None, CanonicalModelIdentity | None, CanonicalModelIdentity | None]:
        """Determine if reviewer is canonically independent from implementer.

        Fails closed: Requires BOTH implementer and reviewer identities to be explicitly proven.
        """
        imp = self.normalize(implementer)
        rev = self.normalize(reviewer)
        if not imp or not rev:
            return False, "DISTINCT_REVIEWER_UNAVAILABLE", imp, rev
        if imp.canonical_name == rev.canonical_name:
            return False, "DISTINCT_REVIEWER_UNAVAILABLE", imp, rev
        if imp.family == rev.family:
            return False, "DISTINCT_REVIEWER_UNAVAILABLE", imp, rev
        return True, None, imp, rev
