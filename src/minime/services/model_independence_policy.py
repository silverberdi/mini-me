"""Policy for ensuring OpenRouter fallback reviewer independence."""

from __future__ import annotations

from minime.services.model_identity_service import CanonicalModelIdentity, CanonicalModelRegistry


class ModelIndependencePolicy:
    """Enforces canonical model and family independence between implementer and reviewer."""

    def __init__(self, registry: CanonicalModelRegistry | None = None) -> None:
        self.registry = registry or CanonicalModelRegistry()

    def validate(
        self, implementer_model: str | None, reviewer_model: str | None
    ) -> tuple[bool, str | None]:
        """Validate that reviewer model is strictly distinct from implementer model by canonical identity and family."""
        ok, reason, _, _ = self.registry.is_independent(implementer_model, reviewer_model)
        return ok, reason

    def select_independent_reviewer(
        self, implementer_model: str | None, allowed_reviewer_models: list[str]
    ) -> tuple[str | None, CanonicalModelIdentity | None]:
        """Select first eligible reviewer model that is canonically independent from the implementer."""
        for candidate in allowed_reviewer_models:
            ok, _, _, rev_identity = self.registry.is_independent(implementer_model, candidate)
            if ok and rev_identity is not None:
                return candidate, rev_identity
        return None, None
