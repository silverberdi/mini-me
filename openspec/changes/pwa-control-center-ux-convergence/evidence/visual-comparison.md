# Candidate-to-reference visual comparison

Candidate application source: `619d044c366a665c8ed670464229343e40b4296f`. Container preview image: `sha256:3ffe4f4ffd80f35b145d2920712bd27a964072482c354ec21d51703a852ab272`. Exact disposable Run/Job, database and screenshot inventory are in `browser/visual-review-6256672911-r10/preview-acceptance-manifest.json`. The side-by-side acceptance board is `browser/visual-review-6256672911-r10/comparison-board.png` (SHA-256 `67ece1a54f55294605e6df2536566992858be530fbd72fbee9cc30ec07ace09a`); its reproducible source page is `browser/visual-review-6256672911-r10/comparison.html`.

All candidate images are real Google Chrome captures from a containerized FastAPI preview connected to a fresh disposable PostgreSQL database at Alembic head. The only durable states seeded/observed were `IMPLEMENTING/RUNNING` and the same Run after the canonical Control Plane `CANCEL` action persisted `CANCELLED`. These are test data, not production observations or human acceptance. No PAUSED, WAITING_CAPACITY, NEEDS_HUMAN or READY_FOR_HUMAN_MERGE state was fabricated. Approved reference images remain unchanged inputs under `docs/design/01..08-*.png`.

| Reference | Candidate evidence | Comparison / result |
|---|---|---|
| 01 desktop active Control Center | `browser/visual-review-6256672911-r10/visual-review-active-desktop-1440x900-landing.png` | Desktop landing shows KPIs before the selected Run list; the detail panel and splitter collapse out of the landing until a user explicitly opens the row, removing the large empty master/detail area. Queue, activity and provider observations follow using only exact test-backend facts. Fixture data remains sparser than the reference, so 4.1 stays open. |
| 02 desktop paused Control Center | None | No authoritative intentional-pause state exists in this fixture. No screenshot or state was manufactured. |
| 03 desktop running Run drawer | `browser/visual-review-6256672911-r10/visual-review-active-desktop-1440x900-drawer.png` | Drawer opens from the selected row and remains bound to the same durable QA Run. Pipeline progress is explicit; secondary server-discovered actions are grouped under a disclosure. The fixture has no candidate/check/review evidence, so the drawer is not visually equivalent to the richer reference. |
| 04 desktop human-merge drawer | None | No durable candidate, independent review and Draft PR bind to a human-merge-ready state. |
| 05 tablet active master/detail | `browser/visual-review-6256672911-r10/visual-review-active-tablet-1024x768.png`, `.../visual-review-active-tablet-768x1024.png` | Master/detail remains selectable and the operational detail is compacted; raw action controls no longer dominate its height. Density and information ordering still differ from the reference. |
| 06 tablet human-review master/detail | None | No candidate-bound independent review authority is present in the disposable lifecycle. |
| 07 mobile active supervision | `browser/visual-review-6256672911-r10/visual-review-active-mobile-390x844.png`, `.../visual-review-active-mobile-360x800.png` | Selected status/attention precede secondary panels; pipeline is collapsed into a concise disclosure, while technical details remain reachable. The full-screen composition still differs from the reference. |
| 08 mobile paused/human attention | None | No authoritative paused state exists. |
| Cancelled terminal state | `browser/visual-review-6256672911-r10/visual-review-cancelled-{desktop,tablet,mobile}-*.png` | Durable `CANCELLED` is displayed as a non-wrapping terminal badge; IMPLEMENTING is labeled as the last observed stage, not active progress, and the action area does not offer an active-looking cancel operation. |
| Mobile notification | `browser/visual-review-6256672911-r10/visual-review-cancelled-mobile-390x844-toast.png` | Chrome geometry assertion confirms the complete toast rectangle ends above the fixed bottom navigation. The notification wraps within its width and height constraints. |

The disposable PostgreSQL browser E2E verified the authenticated UI, candidate/run identity binding, canonical cancellation persistence, stale competing-action denial and screenshot capture at all five approved viewport sizes. Focused Chrome tests separately cover viewport containment, keyboard/focus and accessible names, contrast/theme behavior, authoritative status distinctions, and toast timer ownership. Automated evidence does not replace owner visual review. Tasks 4.1, 6.3 (missing lifecycle states), 6.4 (human review) and 6.6 (authorized post-deployment) remain open.

The screenshot board intentionally scales references and browser captures to a common comparison cell; inspect the originals at native resolution before recording a human verdict. Record the exact result in `evidence/human-validation-checklist.md`; no human result is recorded here.

## Review #6257258048 — R13 targeted visual correction

The focused patch addresses only mobile supervision hierarchy, desktop header/density, and terminal action notification copy. The preview E2E ran in real Chrome against a new disposable PostgreSQL database `minime_pwa_visual_review_20261018_r13`, migrated to the current Alembic head. Its source was the working tree based on `7052b6db02fb3d508470fecfce8652a5fe5e08de`, bound by `source_and_test_worktree_patch_sha256` in the manifest; the image digest and exact synthetic QA Run/Job are also recorded there. The comparison board digest is SHA-256 `5124b298de29e1dc6a6c3df342b8e44c3af60328770b521549ce9248de3f629b`. No production or N01 data was used.

| Review point | R12 evidence | Automated check |
|---|---|---|
| Desktop header and density | `browser/visual-review-6257258048-r13/visual-review-active-desktop-1440x900-landing.png` | Chrome asserts the project label remains accessible but visually hidden, brand layout fits, header groups do not overlap or overflow, and the truthful queue panel uses the full desktop content width. |
| Mobile hierarchy | `browser/visual-review-6257258048-r13/visual-review-active-mobile-390x844.png`, `.../visual-review-active-mobile-360x800.png` | Chrome asserts authoritative RUNNING state and Control Plane-discovered next action appear before technical identifiers; technical disclosure is collapsed and Run/Job IDs are not in visible text. Review authorization labels are Spanish and shown only when enabled by Control Plane. |
| Terminal toast | `browser/visual-review-6257258048-r13/visual-review-cancelled-mobile-390x844-toast.png` | Canonical cancellation persisted as CANCELLED in disposable PostgreSQL; the notification is exactly `Ejecución cancelada.` and excludes Run/Job IDs. Existing action history and detailed status remain intact. |
| Human comparison | `browser/visual-review-6257258048-r13/comparison-board.png`; source `browser/visual-review-6257258048-r13/comparison.html` | Board pairs approved references 01/07 with the real Chrome captures and includes the terminal toast evidence. Visual approval remains pending; 4.1 and 6.4 are not closed. |

The test-owned database and evidence distinguish QA-generated states from product observations. Only `IMPLEMENTING/RUNNING` and the canonical test `CANCELLED` state were exercised; no other lifecycle state was fabricated. Human visual acceptance, missing lifecycle-state E2E, and post-deployment validation remain pending.

## Human owner approval — 2026-10-18 (supersedes historical "pending" for visual UX only)

**Outcome:** `PASS_WITH_KNOWN_DIFFERENCES`. The owner explicitly approved the R13 UX as sufficiently usable to continue, despite intentional visual differences from reference mocks: "aprobado. no son iguales pero iremos validando por el camino". See [PR #156 human visual decision](https://github.com/silverberdi/mini-me/pull/156#issuecomment-6257505220) and the authoritative `evidence/human-validation-checklist.md`.

Reviewed original PR source HEAD: `b60be52a33d5c7c19b5acd643cb939578997078e`.
R13 approved comparison: `browser/visual-review-6257258048-r13/comparison-board.png`. Disposable image digest: `sha256:6ab91632d40990b286c9cd6c9854fdee51950ab8db59aeb89abb07cb13140621`; precommit source patch SHA-256 `fe2265139cc79a3edc92f64f043e7cfb61a46dd2e703cf1bb055f676b7c89c88`.
Refs 01, 03, 05 and 07: human PASS with acknowledged visual differences. Refs 02, 04, 06 and 08: SKIP/DEFER because the disposable backend lacks genuine intentional PAUSED or candidate-bound independent review state. This acceptance closes only scoped UX visual/human gates 4.1 and 6.4; **6.3 remains explicitly open for the missing genuine lifecycle E2E**, and 6.6 remains open for post-authorized merge/deploy. No fictitious data, merge permission or release approval was inferred.

**Integration caution:** R13 screenshots were taken before synchronizing PR #156 with newer `main`; refresh and verify on the exact integrated source SHA before any merge.
