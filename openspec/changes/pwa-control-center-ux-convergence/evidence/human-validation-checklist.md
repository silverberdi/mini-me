# Human visual validation checklist — Control Center

Status: **PREPARED / HUMAN REVIEW PENDING**. Candidate source and immutable preview image identities are now recorded and fresh Chrome comparison captures are available. No human result has been recorded. Do not treat the captures or automated checks as approval.

## Candidate binding

- Candidate application source SHA: `619d044c366a665c8ed670464229343e40b4296f`
- Base SHA: `8564afc51069bd334a67fd19a2a4f51cc0659f5e`
- Container image digest: `sha256:3ffe4f4ffd80f35b145d2920712bd27a964072482c354ec21d51703a852ab272`
- Preview URL: containerized preview was stopped after evidence capture; rerun the named disposable PostgreSQL browser test to create a live preview bound to this source identity.
- Comparison board: `evidence/browser/visual-review-6256672911-r10/comparison-board.png` (SHA-256 `67ece1a54f55294605e6df2536566992858be530fbd72fbee9cc30ec07ace09a`)
- Browser evidence manifest: `evidence/browser/visual-review-6256672911-r10/preview-acceptance-manifest.json`
- Authenticated operator/session: use a disposable authorized test identity; do not record credentials or session tokens.
- Result: `PENDING` (allowed values: PASS / FAIL / SKIP with reason / NOTE).

## Preconditions

1. Verify the preview image digest and source SHA against the bound manifest before review; do not reuse captures after application code changes.
2. Verify the preview points only to disposable PostgreSQL and has a valid test ProjectBinding.
3. Verify the approved reference files `docs/design/01..08-*.png` match the reviewed assets and have not changed.
4. Use only backend-created states and evidence. Do not synthesize PAUSED, READY_FOR_HUMAN_MERGE, review, PR, provider capacity or cost values to fill a screenshot.

## Steps and expected results

1. At 1440×900 compare reference 01 to the authenticated Control Center. Check the active Run, current phase/evidence, queue reason, attention, activity, provider and metric hierarchy. Expected: exact API facts only, Spanish labels, no horizontal overflow or fabricated values.
2. At 1440×900 compare reference 03 after selecting a backend-backed active Run. Check identity, drawer width/backdrop, pipeline, sections, close, Escape and focus restoration. Expected: exact Run/Job/project/repository/candidate binding; unavailable evidence is explicitly unavailable.
3. Inspect references 02 and 08 only if the backend supplies an intentional paused state. Expected: show the server-provided pause cause and safe “Ver condiciones de reanudación”; otherwise record `SKIP` with the exact missing authority. Never create PAUSED for this review.
4. Inspect reference 04 only if a durable candidate, review, checks and Draft PR all bind to the exact candidate. Expected: show pending human decision and consequence; no merge operation is exposed. Otherwise record `SKIP` with missing durable evidence.
5. At 1024×768 and 768×1024 compare references 05/06. Verify master-detail selection, touch operation, candidate identity and review evidence where available. Record missing READY/review authority as `SKIP`; do not substitute mock values.
6. At 390×844 and 360×800 compare references 07/08. Verify supervision-first hierarchy, bottom navigation, attention and readable vertical pipeline. Verify controls are operable without desktop-only actions.
7. In dark and light themes, keyboard through navigation, selected Run, detail tabs and confirmation dialog. Verify visible focus, accessible names, focus containment/return, readable contrast, no clipped critical text and no horizontal overflow. Repeat reflow at 200% browser zoom on desktop/tablet and at a 320 CSS-pixel mobile width.
8. Compare the native reference and candidate screenshots linked in `evidence/visual-comparison.md`. Record each result and deviations there, then enter the overall outcome below. Do not reuse evidence after either application source identity or image digest changes.

Human outcome: `PENDING`. Automated accessibility verification for task 4.2 is recorded as passing in `tasks.md`; this does not replace the owner's visual validation. Tasks 4.1 and 6.4 remain open until the owner records a candidate-bound visual decision and checklist result. Task 6.6 additionally requires separately authorized merge/deployment and is not part of this checklist's completion.
