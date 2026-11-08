# Tasks

## 1. Approved illustration assets

- [x] 1.1 Obtain the ten PNG attachments from the Issue's normative links, verify each file against its assigned visual reference and preserve the exact approved bytes in the existing frontend public asset surface; verify all ten expected files exist with the documented names.
- [x] 1.2 Add a single explicit stage-to-asset mapping for ADMITTED, EXPLORING, PROPOSING, PROPOSAL_REVIEW, IMPLEMENTING, RUNNING_TESTS, VERIFYING, CODE_REVIEW, PREPARING_PR and COMPLETED; verify focused frontend tests assert every exact stage/path pair and no unknown-stage fallback path.

## 2. Current-work card presentation

- [x] 2.1 Reorganize the existing «Trabajo actual» card so the supervision description precedes «Volver a Trabajo», the button label stays on one line at supported widths and the existing router link remains unchanged; verify the component source and frontend tests cover ordering and navigation.
- [x] 2.2 Render the mapped illustration in the card's bounded visual slot with coherent responsive sizing/alignment and decorative semantics (`alt=""`), preserving the existing textual stage/status content; verify tests cover all ten stages, absent runs and unknown stages without broken images.
- [x] 2.3 Confirm no superseded consumer, API contract, status model, route, service-worker rule or dead compatibility path is introduced or left active by this presentation-only change; verify with the focused source/reference checks and the candidate diff.

## 3. Automated and human-facing validation

- [x] 3.1 Run `npm --prefix frontend test` and `npm --prefix frontend run build`; verify both exit 0 and the build contains all ten public illustration assets.
- [x] 3.2 Add or extend Playwright coverage against the served Angular production build for 1440×900, 1024×768, 390×844 and 360×800; verify the real browser observes the selected stage image, decorative semantics, one-line button, unchanged textual stage/status, no horizontal overflow and no broken/false image for missing or unknown stage.
- [x] 3.3 In a real browser compare the redesigned card with the current baseline using the same viewport width and content; verify its total height does not exceed the baseline and record viewport, candidate SHA, served URL, observed image mapping and command/evidence output.
