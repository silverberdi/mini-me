## Context

See `proposal.md` for the user-facing mismatch. The stage metadata and presentation helpers are already shared in `frontend/src/app/shared/pipeline-stage-presentation.ts`. Trabajo Actual renders a responsive grid of labeled stage panels; the Dashboard currently renders a separate row of numbered badges.

## Goals / Non-Goals

**Goals:** Render the Dashboard's ten stage cards with the existing Trabajo Actual panel and badge helpers, preserving the selected Run's stage as the sole source of progress.

**Non-Goals:** Change stage metadata, API data, routes, the robot illustration, or the layout and behavior of Trabajo Actual. No new component, style system, endpoint, or dependency is needed.

## Decisions

- Reuse `getStagePanelClass`, `getStageBadgeClass`, and `PIPELINE_STAGES`; do not create Dashboard-specific status colors or labels.
- Use the same responsive 2/5/10-column grid and card hierarchy as Trabajo Actual inside the compact Dashboard summary. The current implementation's numbered-strip markup is removed as its behavior is replaced.
- Strengthen the existing Playwright coverage to assert labeled cards, state classes and responsive layout. For the active stage illustration, wait for the image and assert `complete` and `naturalWidth > 0`, so an assigned `src` alone cannot pass when the asset is broken.

## Risks / Trade-offs

- Ten labeled cards take more vertical space on mobile than the current number-only strip → use the same mobile-first two-column layout as Trabajo Actual and verify the 360px viewport has no horizontal overflow.
- An illustration URL can be present while the image fails to load → the browser E2E checks successful decoding against the built static asset.
