# Human visual validation — Control Center PR #156

This is a review packet, not an approval record. The owner must inspect the evidence and record PASS/FAIL/SKIP-with-reason/NOTE; no human result has been entered by the implementation agent.

## Candidate identity

- Application source SHA: `94267a842a2259ee75b067931228d417bf3ff16b`
- Base SHA: `8564afc51069bd334a67fd19a2a4f51cc0659f5e`
- Preview image digest: `sha256:14987a30f2c419bd3149b349882825c4ad66f3d580e8baedbf03ee9734427ea9`
- Disposable database: `minime_pwa_control_center_visual_20261018` in test-only container `minime-pwa-acceptance-20261018`; Alembic head `r02_contract_review_budget_identity`; one QA Run and Job seeded by the browser test.
- Durable states shown: `IMPLEMENTING/RUNNING` and the same Run after canonical QA `CANCELLED` only.
- Evidence manifest: `browser/preview-acceptance-manifest.json`.
- Important limit: screenshots contain QA-seeded test data, are not production observations, and do not imply a live scheduler state, review, candidate, merge readiness, or human approval.

## Eight approved visual states

For each available state, compare the reference PNG in `docs/design/` with the named Chrome capture. Record the owner's result and any notes in the final columns.

| # | Approved reference | Candidate evidence | Inspection items | Owner result / notes |
|---|---|---|---|---|
| 01 | `docs/design/01-desktop-active-control-center.png` | `browser/preview-active-desktop-1440x900-qa-seeded.png` | Desktop hierarchy/density, live UNKNOWN vs observed facts, queue/activity/provider layout | Pending human review |
| 02 | `docs/design/02-desktop-paused-control-center.png` | No screenshot; no durable intentional-pause authority exists | Do not infer PAUSED from API health or local UI | SKIP — blocked by absent backend authority |
| 03 | `docs/design/03-desktop-running-run-drawer.png` | `browser/preview-active-desktop-1440x900-qa-seeded.png` | Drawer width, dimmed background, exact Run/Job identity, executor/branch/gate, available evidence | Pending human review |
| 04 | `docs/design/04-desktop-human-merge-drawer.png` | No screenshot; no candidate-bound PR and independent review exist | Do not imply READY_FOR_HUMAN_MERGE | SKIP — blocked by absent candidate/review authority |
| 05 | `docs/design/05-tablet-active-master-detail.png` | `browser/preview-active-tablet-1024x768-qa-seeded.png` | Master-detail selection, compact list, touch/navigation and density | Pending human review |
| 06 | `docs/design/06-tablet-human-review-master-detail.png` | No screenshot; no candidate-bound independent review exists | Do not fabricate review state | SKIP — blocked by absent candidate/review authority |
| 07 | `docs/design/07-mobile-active-supervision.png` | `browser/preview-active-mobile-390x844-qa-seeded.png`, `browser/preview-active-mobile-360x800-qa-seeded.png` | Supervision-first hierarchy, attention, selected identity, no horizontal overflow | Pending human review |
| 08 | `docs/design/08-mobile-paused-human-attention.png` | No screenshot; no durable intentional-pause authority exists | Do not infer PAUSED or offer a synthetic resume action | SKIP — blocked by absent backend authority |

The corresponding `preview-cancelled-*` captures show the same QA Run after the durable Control Plane CANCEL outcome at all five target viewports. They are supplementary 6.3 lifecycle evidence, not substitutes for any of the eight references.

## Interaction/accessibility checklist

The following are automated Chrome evidence already recorded for the candidate; the owner may additionally validate them manually:

- [x] Desktop splitter visible/usable at 1440×900; pointer resize changes the actual master width.
- [x] Keyboard ArrowRight/Home/End; 240 px minimum and 70% maximum respected.
- [x] Collapse persists across reload; reset affects only the active operator's namespaced preference.
- [x] Tablet portrait/landscape and mobile 390/360 widths ignore desktop geometry and hide the splitter.
- [x] Contrast/theme, accessible names, keyboard focus, reduced motion, touch target and narrow reflow checks passed in automated Chrome.
- [ ] Owner has compared the screenshot packet against all available approved references.
- [ ] Owner has recorded candidate-bound visual PASS/FAIL/NOTE for the available states.

## Human decision record

- Reviewer / owner: ____________________
- Date: ____________________
- Overall visual result: `PASS / FAIL / SKIP-with-reason / NOTE`
- Notes / required corrections: ______________________________________________
- Confirmation is bound to application source SHA above and image digest above: `YES / NO`

Task 6.4 remains pending until this section is completed by the human owner. Task 6.6 remains pending until separately authorized merge/deployment and post-deployment verification.
