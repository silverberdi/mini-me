# Design

## Context

See `proposal.md` for the motivation and `specs/` for the observable contract. The current implementation has a FastAPI dashboard service at `src/minime/services/dashboard_service.py`, an existing efficiency service at `src/minime/services/efficiency_telemetry_service.py`, and Angular Dashboard surfaces under `frontend/src/app/features/dashboard/`, including `dashboard.component.ts` and `dashboard-cost-chart.ts`. Existing cost projection is backed by the durable settlement ledger and existing Dashboard E2E coverage includes `frontend/e2e/dashboard-cost.spec.ts` and `frontend/e2e/dashboard-active-change.spec.ts`.

The design must preserve the single API boundary, PostgreSQL as durable state, the existing authenticated Dashboard read path, the existing cost ledger authority, and the current-work summary. It must not introduce a second telemetry database, a client-side token price calculator, or a parallel refresh authority.

## Goals / Non-Goals

**Goals:**

- Produce one bounded, sanitized temporal projection that can be consumed by all three Dashboard dimensions.
- Reuse recorded Run, stage/event, human-gate, project, and liquidated-cost facts; distinguish machine intervals from human waiting intervals.
- Keep aggregation deterministic: a shared ordered bucket axis, explicit missing observations, Global plus attributable project series, and stable project colors derived from existing visual identity data.
- Keep interaction state local to the chart view and accessible through visible legend controls, keyboard-operable buttons, and non-color-only identity cues.
- Replace the superseded five-run chart path after parity is demonstrated, with a removal ledger and focused tests proving no duplicate active authority remains.

**Non-Goals:**

- No new orchestration stages, scheduler behavior, provider, pricing source, production deployment, or change to Trabajo Actual data.
- No invented estimates for missing autonomy, time, or cost; no interpolation that presents an observation as recorded.
- No durable persistence of UI-only toggle, Solo, or hover state.
- No historical rewrite of previously recorded Run, event, gate, or settlement facts.

## Decisions

### 1. One Dashboard telemetry read model, not three independent endpoints

Add the temporal projection to the existing Dashboard service/read path and expose a dimension/window/granularity-shaped payload containing axis buckets, series metadata, points, and no-data status. This keeps authentication, sanitization, refresh, and cost authority in one boundary. Three unrelated endpoints were rejected because they would duplicate aggregation and make cross-dimension interaction drift likely.

### 2. Aggregate from durable facts with explicit interval semantics

Autonomy will use the existing recorded efficiency/progress and retry facts, bounded to 0–100 and weighted so technical retries, same-work loops, and convergence rescues reduce the score while human governance waits remain a classified non-penalty. Delivery time will sum only machine-processing intervals; human-gate intervals will be excluded using persisted stage/event timing and remain available as diagnostic exclusion metadata. Costs will reuse verified liquidated ledger entries and their timestamps, provider/model identity, and precision. A token-based estimate or a synthetic zero fallback is rejected.

### 3. Deterministic time buckets and missing-data semantics

The service will normalize timestamps to the existing application timezone contract, order buckets chronologically, and select daily buckets for the default 30-day window unless the requested window requires weekly density. A point is emitted only when the source facts meet the dimension's verification rules; otherwise the bucket remains absent/unknown rather than being filled with zero or last value. Global aggregation will be computed from the same eligible project observations, not from a separate approximation.

### 4. Chart interaction is a presentation concern

The Angular chart component will own selected-series visibility, Solo selection, and hover emphasis. The backend will return stable series IDs, labels, project IDs, colors or identity tokens, and dimension units; it will not persist ephemeral interaction state. Legend chips will expose toggle and Solo controls independently so keyboard and pointer interactions do not depend on hover alone. A single reusable interaction model will serve all dimensions.

### 5. Safe retirement of the replaced chart path

Before apply, the implementer will inventory callers, templates, styles, tests, and API fields for the current last-five-run chart. After the new projection passes focused unit and browser E2E checks, consumers will be migrated and the obsolete path removed in the same Change. Historical OpenSpec artifacts, durable Run/event/settlement records, and compatibility fields with active consumers remain retained. The removal ledger will record evidence and any `RETAIN-WITH-REASON` item.

## Risks / Trade-offs

- [Risk] Historical data may not contain sufficient interval or retry evidence for every run → [Mitigation] return explicit per-dimension no-data and preserve source-quality metadata; never infer a value.
- [Risk] A large portfolio can make SVG/canvas rendering dense → [Mitigation] bound the window, keep a shared axis, use stable colors plus labels, and validate responsive rendering with the configured Chromium E2E runtime.
- [Risk] Existing dashboard fixtures may omit the new payload → [Mitigation] update only affected fixtures/contracts and retain compatibility defaults that produce an explicit no-data state rather than a fabricated chart.
- [Risk] Different timestamp zones can shift a point across a day boundary → [Mitigation] apply one documented application timezone normalization and test boundary timestamps.
- [Risk] Removing the five-run path before all consumers migrate could regress older Dashboard states → [Mitigation] use static reachability checks, focused regression tests, and remove only after the new authority has real browser evidence.

## Migration Plan

1. Inventory the current Dashboard chart endpoint/fields and all frontend/test consumers; capture the removal ledger as `NONE` or enumerate the superseded path.
2. Implement the projection beside the existing read model, reusing the settlement and efficiency sources, then add focused unit/contract tests for buckets, bounds, exclusions, no-data, and aggregation.
3. Wire the Angular chart and legend to the new payload for all three dimensions; add real Playwright scenarios for multi-series rendering, toggle, Solo, hover attenuation, dimension switching, missing data, and preservation of the active-work summary.
4. Run the bounded relevant checks from `tasks.md`, then remove the old five-run consumers and repeat the checks after removal.
5. Rollback before merge is a Git candidate rollback; no database migration is expected unless the implementation inventory proves a missing durable fact requires one. If a migration becomes necessary, it must be Alembic-based, additive/conservative, reversible, and added through an OpenSpec update before apply.

## Open Questions

None that change the approved scope or contract. The exact existing source fields and component boundaries are implementation details to resolve from the code inventory during Apply.
