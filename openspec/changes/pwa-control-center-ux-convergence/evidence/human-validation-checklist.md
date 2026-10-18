# Human visual validation checklist — Control Center

Status: **PREPARED / NOT RUN**. The reference assets and reproducible steps are ready, but there is no exact committed candidate identity, immutable preview image digest, or human result yet. Do not treat this document or mock-seeded screenshots as approval.

## Candidate binding

- Candidate HEAD SHA: `PENDING_COMMIT`
- Base SHA: `8564afc51069bd334a67fd19a2a4f51cc0659f5e`
- Container image digest: `PENDING_BUILD_FOR_EXACT_HEAD`
- Preview URL: `PENDING_CONTAINERIZED_PREVIEW`
- Authenticated operator/session: use a disposable authorized test identity; do not record credentials or session tokens.
- Result: `PENDING` (allowed values: PASS / FAIL / SKIP with reason / NOTE).

## Preconditions

1. Verify the preview image was built from the exact candidate HEAD and record its immutable digest.
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
8. Record each result and deviations in `evidence/visual-comparison.md`; bind screenshots and any browser trace to the exact candidate SHA and preview digest. Do not reuse evidence after either identity changes.

Human outcome: `PENDING`. Tasks 4.1, 4.2 and 6.4 remain open until all required checks have actual evidence and the owner records the candidate-bound decision. Task 6.6 additionally requires separately authorized merge/deployment and is not part of this checklist's completion.
