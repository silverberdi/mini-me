# Tasks: PWA Control Center

## Slice 017.1 — PWA App Shell + Overview + Queue Observability
- [ ] 1.1 Create CSS design tokens (`tokens.css`, `layout.css`, `components.css`) and modular directory layout under `src/minime/static/`.
- [ ] 1.2 Implement top navigation header with brand identity, live system health, scheduler mode (`RUN`/`DRAIN`/`WAIT`), and auto-refresh controls.
- [ ] 1.3 Build KPI summary grid displaying active runs, queue depth, READY/blocked counts, and attention alerts.
- [ ] 1.4 Implement autonomous queue prioritization panel with ranked candidate list, base scores, starvation aging, dependencies, and explainable refusal codes.
- [ ] 1.5 Write automated frontend and API integration tests for App Shell, Overview, and Queue telemetry.

## Slice 017.2 — Runs + Attention + Pipeline Observability
- [ ] 2.1 Implement live orchestration runs table with status filtering, stage badges, and selection handling.
- [ ] 2.2 Build visual pipeline stepper widget displaying stage progression (`WORKTREE_SETUP` → `IMPLEMENTATION` → `CHECKS` → `REVIEW` → `AUDIT` → `PREVIEW` → `PR` → `MERGE_GATE` → `CLOSURE`).
- [ ] 2.3 Implement active jobs detail pane showing executor role, attempt counts, blocker claims, and transition history.
- [ ] 2.4 Build prominent Attention Banner for human gates (`NEEDS_HUMAN`) and critical blockers with direct drill-down links.
- [ ] 2.5 Write automated tests verifying run state transitions, pipeline stepper states, and attention banner rendering.

## Slice 017.3 — Candidates + Checks + Review + Audit
- [ ] 3.1 Implement candidate authority inspector displaying generation lineage, base/head SHA, and authority status (`CURRENT`, `FROZEN`, `SUPERSEDED`).
- [ ] 3.2 Build deterministic checks runner viewer displaying per-check command, exit code, duration, and output logs.
- [ ] 3.3 Build complementary review panel rendering reviewer identity, verdict (`READY_TO_MERGE`, `CHANGES_REQUESTED`), and structured findings.
- [ ] 3.4 Build DeepSeek audit panel displaying verdict (`PASS`, `FAIL`), risk rating, and audit analysis.
- [ ] 3.5 Implement visual indicator distinguishing current evidence from stale candidate bindings.
- [ ] 3.6 Write automated tests verifying candidate inspection, checks, review, and audit rendering.

## Slice 017.4 — Preview + Guided UI Validation
- [ ] 4.1 Integrate 013 Container Preview lifecycle widget (`BUILDING`, `PROBING`, `READY`, `FAILED`, `STOPPED`) with live port mappings and preview URL launcher.
- [ ] 4.2 Implement guided validation checklist UI rendering scenario steps, PASS/FAIL action buttons, and evidence note input.
- [ ] 4.3 Enforce strict candidate binding (`head_sha`, `base_sha`, `image_digest`) and render `STALE` status when authority changes.
- [ ] 4.4 Write automated tests verifying container preview lifecycle transitions and guided validation submissions.

## Slice 017.5 — Operator Actions Control Plane Integration
- [ ] 5.1 Implement dynamic action discovery consuming `/api/v1/control-plane/actions/available`.
- [ ] 5.2 Build contextual operator action toolbar (Resume, Retry, Reassign, Resolve Gate, Cancel, Preview Actions).
- [ ] 5.3 Implement accessible confirmation modal with clear impact explanation and optimistic mutation execution.
- [ ] 5.4 Build live operator action audit trail panel.
- [ ] 5.5 Write automated tests verifying action discovery, execution, optimistic UI updates, and error handling.

## Slice 017.6 — Orchestration History + GitHub + Provider Observability
- [ ] 6.1 Implement historical runs archive with search, filter, and execution timeline drill-down.
- [ ] 6.2 Build GitHub synchronization widget displaying Issue #, Project item status, and PR remote links.
- [ ] 6.3 Build provider health & capacity grid showing status (`AVAILABLE`, `UNAVAILABLE`, `RATE_LIMITED`), latency, and spend.
- [ ] 6.4 Write automated tests verifying history queries, GitHub telemetry, and provider capacity rendering.

## Slice 017.7 — Responsive Viewport Optimization + UX Polish
- [ ] 7.1 Implement Desktop Standard (~1366x768) and Large/Ultrawide (>=1920px) 3-column split layout eliminating dead space.
- [ ] 7.2 Implement Tablet (~1024x768) 2-column responsive layout with collapsible drawers.
- [ ] 7.3 Implement Mobile (~390x844) single-column layout with sticky header, bottom navigation bar, and accessible touch targets.
- [ ] 7.4 Verify WCAG 2.1 AA accessibility (keyboard focus trapping in dialogs, ARIA labels, high-contrast text, color-independent badges).
- [ ] 7.5 Write responsive layout automated tests verifying multi-viewport rendering without layout breakage or clipping.

## Slice 017.8 — PWA Web App Manifest + Service Worker + Final Acceptance
- [ ] 8.1 Create W3C Web App Manifest (`manifest.webmanifest`) and standard PWA app icons (`192x192`, `512x512`).
- [ ] 8.2 Implement Service Worker (`sw.js`) with cache-first static shell strategy and network-first API handler.
- [ ] 8.3 Implement degraded / offline status banner with automatic reconnection polling.
- [ ] 8.4 Run full automated test suite (backend pytest, frontend unit/static tests, Ruff, formatting, Alembic heads, OpenSpec strict validation).
- [ ] 8.5 Perform real browser inspection across desktop, tablet, and mobile viewports.
