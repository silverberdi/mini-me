# Human visual validation checklist — Control Center

## Owner decision — ACCEPTED WITH KNOWN DIFFERENCES

**Decision:** `PASS_WITH_KNOWN_DIFFERENCES` for available R13 views, recorded from the owner's explicit instruction on 2026-10-18: "aprobado. no son iguales pero iremos validando por el camino".

This is genuine **human visual approval** of the currently observable UI, **not** pixel-perfect equivalence, approval of unavailable state implementations, execution of tests on production, or authorization to merge/deploy. The older R10 `PENDING` evidence is superseded only for the visual decision below.

### Immutable evidence binding

- PR: [#156](https://github.com/silverberdi/mini-me/pull/156)
- Source PR HEAD reviewed: `b60be52a33d5c7c19b5acd643cb939578997078e`
- R13 preview source base (before the final patch was committed): `7052b6db02fb3d508470fecfce8652a5fe5e08de`
- R13 source-and-test working tree patch SHA-256: `fe2265139cc79a3edc92f64f043e7cfb61a46dd2e703cf1bb055f676b7c89c88`
- Historical branch base SHA at capture: `8564afc51069bd334a67fd19a2a4f51cc0659f5e`
- Container preview image digest: `sha256:6ab91632d40990b286c9cd6c9854fdee51950ab8db59aeb89abb07cb13140621`
- R13 board: `evidence/browser/visual-review-6257258048-r13/comparison-board.png`
- R13 manifest: `evidence/browser/visual-review-6257258048-r13/preview-acceptance-manifest.json`
- QA database: `minime_pwa_visual_review_20261018_r13`, disposable and migrated to Alembic head; backend-observed states `IMPLEMENTING/RUNNING` and `CANCELLED` only.
- Human decision provenance: [PR #156 recorded authorization](https://github.com/silverberdi/mini-me/pull/156#issuecomment-6257505220).

**Integrity note:** the QA image was built from a patch-bearing worktree based on `7052b6db...` before source commit `b60be52a...`. The manifest preserves the exact patch digest. After synchronization with newer `main`, retest on the *integrated source SHA*; do not reuse the R13 image as proof of integrated or deployed behavior.

### Reference-by-reference decision

| Approved visual reference | Outcome | Evidence / accepted limitation |
|---|---|---|
| 01 — desktop active Control Center (1440×900) | **PASS WITH DIFFERENCES** | R13 authenticated landing; layout/queue/header accepted. QA data is intentionally sparse, so dense live telemetry in the approved reference cannot be demonstrated. |
| 02 — desktop paused Control Center | **SKIP — authority unavailable** | No real, durable intentional `PAUSED` state in the disposable backend. |
| 03 — desktop running Run drawer (1440×900) | **PASS WITH DIFFERENCES** | R13 selected real QA Run and Control Plane actions; no authentic candidate/checks/review data present. |
| 04 — desktop human merge drawer | **SKIP — authority unavailable** | No real candidate bound to independent review + PR ready for human merge. |
| 05 — tablet active master-detail (1024×768, 768×1024) | **PASS WITH DIFFERENCES** | R13 master-detail with real QA identity and bounded responsive controls. |
| 06 — tablet human-review master-detail | **SKIP — authority unavailable** | No canonical candidate-bound independent review in test backend. |
| 07 — mobile active supervision (390×844, 360×800) | **PASS WITH DIFFERENCES** | R13 status/attention/authorized next actions first; technical IDs progressively disclosed. |
| 08 — mobile paused/human attention | **SKIP — authority unavailable** | No authentic intentional PAUSED/attention authority in disposable lifecycle. |
| Supplementary terminal `CANCELLED` | **PASS WITH DIFFERENCES** | Canonical Control Plane cancellation persisted in disposable PostgreSQL; toast is concise Spanish `Ejecución cancelada.`, without IDs or bottom-navigation obstruction. |

### Automated checklist / validity boundaries

- **PASS (agent-reported, not human-operated):** one real-Chrome + disposable PostgreSQL integration test and four focused browser tests at R13, covering viewport, accessibility/theme, action presentation and toast. OpenSpec strict, Ruff, JS syntax and diff checks reported PASS.
- **NOT VERIFIED by this decision:** complete browser E2E for genuine `PAUSED`, `WAITING_CAPACITY`, `NEEDS_HUMAN`, recovery/UNKNOWN and candidate-bound `READY_FOR_HUMAN_MERGE`. Track explicitly in OpenSpec task **6.3** and future canonical lifecycle evidence; never fabricate statuses to pass a screenshot.
- **NOT AUTHORIZED:** PR merge, production deployment, scheduling policy changes, model inference, pilot continuation or editing PR #160. OpenSpec task **6.6** remains pending post-authorized merge/deploy.
- **Next integration gate:** bring PR #156 onto the current main without discarding existing design assets, then run affected API/browser/security/Control Plane regressions with a valid disposable environment. Record integrated source SHA and new evidence, and seek separate human merge authorization.

**Human outcome:** `PASS_WITH_KNOWN_DIFFERENCES` — available views accepted, deferred states explicitly SKIPPED for absence of legitimate authority. No further speculative visual redesign requested.
