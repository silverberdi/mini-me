## Context

See [proposal.md](proposal.md) for the motivation and scope. The active implementation has two distinct responsibilities entangled in `BudgetService`: optional reviewer spend controls and the legacy OpenRouter daily/monthly policy. The ledger and reservations also support review evidence and reconciliation, so deleting the full budget subsystem would remove useful behavior beyond this Issue.

The provider fallback path is currently gated in project profile resolution, execution preflight, and a legacy eligibility evaluator. Separate API, CLI, frontend, and active OpenSpec projections expose cap/headroom data. Migration `006_openrouter_budget.py` is historical and immutable.

## Goals / Non-Goals

**Goals:**

- Remove the legacy cap as a provider dispatch prerequisite through all live consumers.
- Keep configured fallback identity and in-flight eligibility checks intact; distinguish provider-originated failures from local checks.
- Keep actual usage/cost evidence and optional reviewer-specific limits where still used.
- Retire only obsolete policy persistence through a forward-only migration.

**Non-Goals:**

- Change the rector's provider-role policy, authorize exceptional spend, or redefine when a provider is considered exhausted.
- Change any project application, deploy Mini Me, or start/retry a project Run.
- Rewrite historical migrations or archived OpenSpec changes.

## Decisions

1. **Keep spend evidence; remove cap authority.** Retain the minimal reservation/ledger data needed for provider usage, unknown outcomes, and direct reviewer accounting. Remove `OpenRouterBudgetPolicy`, its daily/monthly cap configuration and project-level authorization switches only after all live consumers are migrated. Do not delete spend persistence that still supports reviewer evidence and reconciliation.

2. **Make role configuration the fallback selector.** Resolve a configured fallback profile without requiring `fallback_authorized`, `openrouter_drain_allowed`, or a budget row. The dispatch policy still independently enforces the contract's in-flight, provider-capacity, role, candidate, and pipeline invariants. A missing/unconfigured profile remains a no-dispatch condition; provider quota/auth/rate-limit outcomes remain truthful provider failures.

3. **Remove projections rather than rename caps.** Remove daily/monthly cap and headroom fields from API/CLI/UI responses and settings. Preserve usage/cost fields only where they represent persisted provider observations, with source and time where available; do not derive percentage or pretend provider balance.

4. **Migrate conservatively.** Add a new Alembic revision after the current head. Drop only the obsolete OpenRouter cap policy table and project authorization column after their consumers are removed; retain append-only historical migrations and usage evidence. Remove legacy authorization keys from project execution-policy JSON only where this can be done without overwriting unrelated settings.

5. **Prove routing and failure boundaries at the service integration.** Tests must show a configured eligible in-flight fallback dispatches with no legacy policy row, and that missing configuration, ineligible stage, a single primary available, or provider-native rejection does not silently fall through. Preserve independent-review and DeepSeek credential boundaries.

## Risks / Trade-offs

- [Removing local caps can expose the account to provider charges up to the provider's own limits] → use only the operator-configured fallback role and preserve any explicit exceptional-cost human gate from the rector; do not invent a new daily/monthly threshold.
- [A forgotten consumer can continue blocking or displaying false headroom] → search source, active specs, frontend, CLI, API, migrations and tests; add a regression check for absence of the legacy policy prerequisite.
- [Removing the policy table discards obsolete cap settings] → retain immutable usage/ledger history and document that those cap values no longer govern runtime behavior.
- [Provider usage may be unavailable after a timeout] → retain unresolved evidence as unknown; never claim zero cost or fabricate a balance.

## Migration Plan

1. Update live specifications and code paths, then remove cap configuration and obsolete projections.
2. Add a conservative Alembic revision after the current migration head; retain `006_openrouter_budget.py` unchanged.
3. Verify migrations on the authorized PostgreSQL test database and exercise provider dispatch integration against controlled provider adapters. Real-run evidence remains deferred to the final validation batch as instructed.
4. Rollback uses the application/database rollback before deployment. A downgrade may restore schema but cannot recover removed cap settings; provider usage/ledger evidence remains retained.
