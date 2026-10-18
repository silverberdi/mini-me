## 1. Baseline and contract verification

- [ ] 1.1 Capture the isolated worktree base/head SHAs, current PWA routes, schemas, auth behavior, every loaded script/style and DOM/event/API consumer, module imports, duplicate refresh/listener owners, service-worker cache behavior and relevant tests; attach the inventory to Change evidence without unrelated application changes.
- [ ] 1.2 Implement the owner's approved backend-only observer for the fixed `minime-scheduler.service` using existing unprivileged read-only systemd access; report active/substate, boot enablement and logical admission separately, with source/time/age. Prove one-second timeout, 30-second freshness, UNKNOWN on inaccessible/stale/unsupported evidence, and no caller-selected unit, command execution, added privilege or control operation.
- [ ] 1.3 Validate actual dashboard, queue, scheduler, provider, budget, efficiency, actions, preview, validation and auth response schemas against OpenAPI/Pydantic and write field-to-view mappings; reject any field without an authoritative source.
- [ ] 1.4 Before implementation, verify MM-R03–MM-R06 dependency contracts/read models are stable; if they are not complete, preserve this Change as a proposal and do not begin apply or duplicate their authorities.

## 2. Converged Control Center shell and read models

- [ ] 2.1 Implement the single Spanish shell and coherent navigation using the existing FastAPI route, CSS tokens, theme support and native module stack; preserve current Backlog, Projects and execution workflows.
- [ ] 2.2 Bind overview, queue, attention, providers, activity and metrics to the existing authenticated APIs; show freshness and explicit UNKNOWN/stale/error states without client-side admission, capacity, cost or status calculations.
- [ ] 2.3 Add only the additive dashboard read-model fields proven necessary by task 1.3; include auth/permission and stale-evidence contract tests; do not add a persistence migration unless OpenSpec update approves a demonstrated need.

## 3. Run/Job detail and governed operator actions

- [ ] 3.1 Implement the contextual Run/Job detail drawer with exact repository/project/change/Run/Job and candidate identity plus overview, pipeline, checkpoints, Git/diff, checks, review, logs/events, preview and cost sections backed by existing read models.
- [ ] 3.2 Preserve candidate/generation isolation, redact/escape diagnostics, and distinguish RUNNING, intentional PAUSED, WAITING_CAPACITY, NEEDS_HUMAN, UNKNOWN, AUTH_REQUIRED, RECOVERY and READY_FOR_HUMAN_MERGE without collapsing states.
- [ ] 3.3 Wire action discovery, parameters, confirmation, optimistic-concurrency identity, action result and history through the existing Control Plane; test stale/forbidden/duplicate rejection and prove no merge or direct CLI/Git/systemd/provider path exists.
- [ ] 3.4 Integrate preview and human validation using existing APIs, exact candidate/image identity and stale invalidation; verify UI shows the persisted result only after authority response.

## 4. Responsive, accessible and privacy-safe PWA

- [ ] 4.1 Implement the approved desktop, tablet and mobile information hierarchy and interaction patterns at 1440×900, 1024×768, 768×1024, 390×844 and 360×800, retaining both supported themes and Spanish labels.
- [ ] 4.2 Verify keyboard order, visible focus, dialog focus behavior, accessible names/landmarks, text-plus-icon states, contrast, zoom/reflow, reduced motion, touch targets and no destructive truncation at every target viewport.
- [ ] 4.3 Change the service worker to an explicit safe static-resource allowlist, stop all `/api/*` and authenticated/Control Plane CacheStorage reads/writes and offline replay, invalidate only its owned old shell cache, and verify offline/reconnect/auth expiry/logout plus two-session isolation and per-panel freshness in a real browser.

## 5. Regression, migration and Removal Gate

- [ ] 5.1 Migrate every live consumer identified in the design ledger—auth/profile, global/mobile navigation, theme/refresh/visibility, Backlog list/detail/DoR/all mutations and clarification, Projects/onboarding/context, KPI/attention/queue/providers, Runs/changes/filters, every detail tab, preview/validation, GitHub/efficiency, Control Plane discovery/confirmation/execution/history, timeline/dialog/toast/offline—to the modular Control Center. Assign one bootstrap/state/render/polling owner and one listener owner per control; document runtime/import/DOM/event/API call-graph parity before retiring the legacy IIFE.
- [ ] 5.2 After domain-by-domain parity evidence, remove the legacy script include and IIFE plus only demonstrably orphaned modules, wrappers, CSS selectors and cache paths listed in the Removal Ledger; retain justified shared modules and historical 017 artifacts, and obtain explicit human approval for any RETAIN-WITH-REASON exception.
- [ ] 5.3 After removal, rerun affected dashboard/PWA/API/queue/control-plane/auth regressions and browser interactions at all five viewports; verify exactly one bootstrap, refresh schedule, subscription and listener owner, no active legacy renderer, no `/api/*` CacheStorage reads/writes, and no cross-session operational data exposure.

## 6. Stage E2E, full-value E2E and release evidence

- [ ] 6.1 Prove the authenticated read stage in a disposable containerized preview: API facts render with correct project/Run/candidate identity; 401/403, missing, stale, unknown, malformed and offline cases do not leak or fabricate state.
- [ ] 6.2 Prove the governed action stage with a permitted QA action and denied/stale competing request; correlate action request/result, expected state and browser-visible final state without touching production or enabling scheduler policy.
- [ ] 6.3 Execute full-value browser E2E for active Run, deliberate pause, WAITING_CAPACITY, NEEDS_HUMAN, READY_FOR_HUMAN_MERGE and recovery/UNKNOWN on the same backend model across desktop/tablet/mobile; capture redacted traces/screenshots and verify no action bypass or merge.
- [ ] 6.4 Complete the preview human-validation checklist with preconditions, numbered steps and expected results, bound to exact candidate head SHA, base SHA and immutable image digest; record PASS/FAIL/SKIP-with-reason/NOTE without reusing stale evidence.
- [ ] 6.5 Run configured API/UI/security/static checks and document failures honestly; no screenshot fixture, mock response or health-only result counts as full E2E.
- [ ] 6.6 After authorized human merge/deployment, verify the real authenticated PWA route and changed functionality in a browser, repeat critical responsive/auth/action and stale-data scenarios, bind evidence to deployed SHA/image digest, and confirm no scheduler policy/state was changed by this Change.

## 7. Scheduler observation and privacy regression evidence

- [ ] 7.1 Exercise backend scheduler projection against active/enabled and inactive/disabled observations, verifying independent logical admission mode and source timestamps; inject inaccessible, stale, timeout, unsupported, malformed and contradictory observations and prove `UNKNOWN` without inferring from API/PostgreSQL health.
- [ ] 7.2 In a real browser, inspect CacheStorage and network behavior for static shell, authenticated GETs, `/api/v1/auth/*`, Control Plane actions, 401/403, offline, reconnect and logout/login across two sessions; prove only allowlisted static assets persist and operational values remain unavailable until fresh reads.
