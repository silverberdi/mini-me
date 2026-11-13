## Why

Mini Me can block configured provider use because of a legacy project budget row, daily/monthly caps, breach flags, and a separate authorization switch that are not part of the rector contract. This change removes those artificial admission gates while preserving provider-native quota/auth failures, the configured fallback role and its in-flight safety rules, human authority over exceptional cost decisions, and truthful durable spend evidence.

## What Changes

- Remove mandatory Mini Me daily/monthly caps, per-project OpenRouter budget authorization rows, and their breach/headroom checks as prerequisites for configured provider dispatch.
- Treat the operator-configured provider role/profile as the ordinary provider selection; preserve the OpenRouter rescue eligibility and pipeline safeguards defined by the rector contract, including in-flight-only use, verified exhaustion of the provider assigned to the blocked execution stage, exact fallback profile identity, and no reviewer or new-work bypass.
- On actual provider quota, balance, rate-limit, credential, or model failures, report the observed provider outcome and preserve the in-flight work; do not disguise a local artificial cap as a provider failure or silently substitute another provider.
- Preserve provider-reported usage, cost, source, and observation time as durable evidence; retain unresolved outcomes and historical ledger data without using them as invented daily/monthly admission limits.
- Remove obsolete budget controls and projections from active specs, configuration, APIs, CLI, UI, and persistence where no remaining consumer needs them; preserve history and any separate explicitly configured reviewer controls required by the rector contract.
- Add integration evidence that configured fallback dispatch is not blocked by absent/zero legacy cap policy, while provider-native rejection and all fallback eligibility constraints remain enforced.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `budget-spend-tracking`: replace cap enforcement and budget reservation requirements with truthful provider usage/cost evidence and unresolved-outcome handling.
- `openrouter-drain-fallback`: remove artificial policy/headroom prerequisites while preserving strict fallback eligibility, provider outcomes, and role separation.
- `scheduler-capacity-policy-convergence`: remove budget-cap conditions from in-flight fallback while preserving DRAIN and admission boundaries.
- `greenfield-project-bootstrap`: remove separate budget authorization as a prerequisite when provider role/profile is configured.
- `project-agent-configuration`: treat the operator-configured fallback role as the authorization for ordinary fallback selection; remove artificial cap approval.
- `scheduler-capacity-lifecycle`: remove budgeted-fallback predicates while preserving capacity modes and no-new-work rules.
- `projection-purity-and-cqs`: align spend/usage projections with observed provider facts rather than artificial cap/headroom calculations.
- `transaction-and-concurrency-contract`: remove serialization guarantees that exist solely to enforce artificial caps while preserving transactional integrity for retained usage evidence.

## Impact

Affected active OpenSpec capabilities; provider policy and execution services; project configuration/bootstrap; OpenRouter status and spend APIs, CLI and frontend; PostgreSQL models/repositories and a forward-only conservative Alembic migration; tests for provider dispatch, spend evidence, configuration, projections, and concurrency. Historical migrations and archived Changes remain immutable. No project application, deployment, production data, or user Run is changed by this Change.
