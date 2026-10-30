# Tasks

## 1. Baseline and migration boundary

- [ ] 1.1 Inventory the legacy frontend entrypoints, routes, components, forms, state, HTTP calls, listeners, timers, pollers, caches, service-worker behavior, consumers and browser tests; verify the Removal Ledger identifies each retained, migrated or removable item and records the baseline commit.
- [ ] 1.2 Capture the existing API contracts, authentication flow, authorization failures, stale-state behavior and F7 capability responses; verify contract fixtures and traceability point to FastAPI/Control Plane authorities without adding a second API or client-side business authority.
- [ ] 1.3 Define the temporary Angular/legacy coexistence flag, rollback path and retirement gate; verify F8 remains disabled until explicit operator authorization and no implementation, deployment, scheduler execution or spend starts during planning.

## 2. Angular application shell and typed client

- [ ] 2.1 Create the Angular + TypeScript + Tailwind application shell with secure content handling and the existing public manifest metadata; verify the production build succeeds and the manifest exposes the required standalone and icon metadata.
- [ ] 2.2 Implement one typed HTTP client against the existing API contracts, with backend-validated authentication, authorization, stale-state and error handling; verify unit/contract tests cover accepted, unauthorized, forbidden and obsolete-state responses without exposing secrets.
- [ ] 2.3 Implement the single bootstrap and refresh lifecycle with manual and 5s/10s/30s intervals; verify browser instrumentation shows one timer/listener lifecycle, immediate read on interval change, no mutation during polling and teardown on navigation/logout.
- [ ] 2.4 Implement authenticated navigation with exactly five independent routes—Dashboard, Trabajo, Trabajo actual, Proyectos and Backlog—and only Dashboard and Proyectos as primary destinations; verify deep links, refresh, back/forward and forbidden or missing context fail explicitly without selecting another Run.

## 3. View and interaction parity

- [ ] 3.1 Migrate Dashboard, Trabajo and Trabajo actual components, forms and state while preserving verified health, attention, progress, quota and no-data semantics; verify browser E2E shows source, unit, scope, observation time and freshness and never fabricates missing values.
- [ ] 3.2 Migrate Proyectos and contextual Backlog navigation with authorized project and Request/Run/stage context; verify browser E2E preserves project detail links, Request traceability and backend rejection of unauthorized or obsolete mutations.
- [ ] 3.3 Migrate analog progress/quota gauges and the three-dimension effectiveness chart; verify chart tests preserve separate scales, provider/model attribution, missing-data explanations and text alternatives without client-side measurements.
- [ ] 3.4 Preserve F7-governed controls and deferred pause semantics; verify unavailable capabilities remain accessible, visibly disabled with their explanation and emit no request or success confirmation.

## 4. Responsive, accessible and safe PWA behavior

- [ ] 4.1 Implement Tailwind responsive layouts for desktop, tablet and mobile, including tablet master/detail and mobile focused navigation; verify real browser runs cover 2560px, desktop, 1024x768, 768x1024, 390x844 and 360x800 without horizontal content loss.
- [ ] 4.2 Implement keyboard/screen-reader access, visible focus, contrast, touch targets, zoom/reflow and accessible chart/error/disabled-state text; verify automated accessibility checks plus human validation scenarios at 200–400% zoom on the Angular candidate.
- [ ] 4.3 Configure the service worker to cache only the public static shell; verify cache inspection finds no authenticated responses, credentials or operational bodies, logout clears authenticated memory, and obsolete shell caches retire on update.
- [ ] 4.4 Handle offline, stale and reconnection states without queued or replayed mutations; verify real browser E2E blocks actions offline, labels retained observations with timestamps, refreshes authoritative reads after reconnection and permits actions only after current authority is verified.

## 5. Parity evidence and safe retirement

- [ ] 5.1 Execute a current candidate-vs-legacy parity matrix for all five routes, navigation, data, actions, security refusals, accessibility, responsive behavior, PWA/offline behavior and F7 controls; verify every result is bound to immutable candidate/base SHAs, commands, exit codes, screenshots and observed effects.
- [ ] 5.2 Measure comparable Angular and legacy bundle size, load/performance, memory and browser behavior on the agreed devices; verify results identify methodology, units, scope and any unmet gate, without inventing thresholds or declaring parity from incomplete evidence.
- [ ] 5.3 Run real browser E2E against authorized isolated services, including authentication, allowed actions, forbidden/obsolete mutations, logout/reconnect and all route transitions; verify mocked APIs and executor reports alone are rejected as insufficient evidence.
- [ ] 5.4 Review the parity matrix and human visual validation independently; verify legacy remains active when any required evidence or consumer is missing and retirement requires explicit approval after all gates pass.
- [ ] 5.5 Migrate approved consumers to the Angular entrypoint and remove only ledger-identified legacy entrypoints, configuration, listeners, pollers and tests; verify post-retirement E2E passes, no duplicate listeners/pollers remain, and the legacy rollback path is no longer an active interface.

## 6. Governance and delivery evidence

- [ ] 6.1 Preserve the backend, API contracts, durable models, business rules, ticket provider, control plane and permissions as authorities; verify the diff contains no backend rewrite, second API, second execution engine or parallel backlog.
- [ ] 6.2 Complete the authorized OpenSpec Apply/Verify lifecycle with real tests and current evidence; verify the implementation candidate and evidence are tied to the exact Change, Request, worktree and immutable SHA, with no F8 work performed before operator authorization.
- [ ] 6.3 Prepare the implementation and documentation delivery through the native review, PR, Sync and Archive workflows; verify the disabled/planned F8 boundary, retirement decision, evidence links and remaining rollback information are recorded before any ticket closure.
