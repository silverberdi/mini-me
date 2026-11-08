# Design

## Context

See `proposal.md` for motivation. The affected route is the standalone Angular `TrabajoActualComponent`; it already exposes the selected run, its stage and the existing «Volver a Trabajo» link. The capability `pwa-responsive-and-offline-pwa` already governs responsive behavior and public-shell boundaries. This Change is presentation-only and must not alter the API, run state, service-worker policy or navigation model.

## Goals / Non-Goals

**Goals:**

- Keep the current-work card's textual state and navigation behavior intact while changing only its visual composition.
- Store the ten approved PNGs as public static assets and resolve them through one explicit stage-to-file authority.
- Preserve decorative semantics, responsive reflow, keyboard/screen-reader usability and a bounded card height.
- Provide deterministic source-level and real-browser validation for all mappings, fallback behavior and supported viewport widths.

**Non-Goals:**

- No API, domain model, persistence, orchestration-stage, status semantics or route changes.
- No new asset generation, visual substitution, remote image dependency, service-worker cache rule or authenticated-data storage.
- No global card redesign outside the «Trabajo actual» header/card.

## Decisions

1. **Use an explicit stage-to-asset map.** The component will map each exact stage key to its assigned filename from the Issue table: `ADMITTED→admitted.png`, `EXPLORING→exploring.png`, `PROPOSING→proposing.png`, `PROPOSAL_REVIEW→proposal-review.png`, `IMPLEMENTING→implementing.png`, `RUNNING_TESTS→running-tests.png`, `VERIFYING→verifying.png`, `CODE_REVIEW→code-review.png`, `PREPARING_PR→preparing-pr.png`, and `COMPLETED→completed.png`. A lookup result is used only for recognized stages; unknown or absent stages render no illustration rather than guessing.

2. **Keep assets in the existing public shell.** The exact PNG attachments are copied into the existing Angular public asset surface, with stable local paths and no runtime download from GitHub. This keeps the images available to the built PWA without expanding API or authenticated caching boundaries. Any source asset acquisition must preserve the approved files byte-for-byte and be recorded in implementation evidence.

3. **Recompose the existing header with CSS layout only.** The description remains the textual anchor, the illustration occupies the existing visual area in a bounded media slot, and the link is placed below the description with whitespace-nowrap/flex-shrink constraints appropriate to the supported widths. Avoid a second card, a new component hierarchy or a layout measurement service; compare rendered heights in browser validation at the same content and viewport widths.

4. **Treat the image as decorative.** The image receives an empty accessible name (`alt=""`) and is excluded from the semantic stage/status message. The existing heading, description, stage badge and status content remain the source of meaning, including when no mapped image is available.

5. **Validate in layers.** Add focused frontend tests for the explicit mapping, all ten stage keys, fallback and structural ordering; run the existing frontend test/build commands. Add or extend Playwright coverage against the served Angular build for desktop, tablet and mobile widths, checking button one-line rendering, image source/decoration, no horizontal overflow and card height parity. A source test alone does not qualify as browser evidence.

## Risks / Trade-offs

- [An attachment could be downloaded with the wrong stage filename or altered] → Verify every asset against the Issue assignment and visual reference before applying; assert all ten exact paths in tests and retain browser evidence.
- [The button or illustration could overflow at narrow widths] → Use bounded responsive layout rules and real-browser checks at 360px/390px and tablet widths; fail closed on horizontal overflow or multi-line button text.
- [Unknown run data could produce a broken image] → Make the lookup nullable and render the media slot safely without a guessed fallback.
- [Adding public PNGs could increase the shell size] → Reuse the existing public asset surface, optimize only if byte-equivalent approval is preserved, and measure the production build rather than adding a new image dependency.

## Migration Plan

No database or deployment migration is required. Apply the component/assets/tests change, validate the production build and browser scenarios, and roll back by reverting the same frontend commit if visual validation fails. The service-worker and API contracts remain unchanged.
