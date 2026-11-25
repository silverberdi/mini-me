## 1. Persistence and configuration

- [x] 1.1 Add the minimal PostgreSQL/Alembic persistence for global Watchdog settings and candidate-bound diagnosis records with optional suggestion/status; preserve safe defaults when no settings row exists.
- [x] 1.2 Add authenticated API operations to read/update global settings from the registered provider/model catalog and return persisted values without credentials; selections are validated against the transversal union of enabled/available registry models and stage-selectable Codex/Antigravity models from the global agent catalog.
- [x] 1.3 Add focused PostgreSQL integration coverage for settings defaults/update, diagnosis idempotency, suggestion status, and migration upgrade on the configured test database.

## 2. Stall detection and canonical recovery

- [x] 2.1 Integrate cheap inactivity evaluation into the existing scheduler/reconciliation path using persisted stage/activity and process evidence; prove progressing runs cause no model invocation or mutation.
- [x] 2.2 Persist sanitized, candidate-bound diagnosis evidence and invoke the configured model only for observed stalls; verify unavailable model capacity does not block mechanically proven playbooks.
- [x] 2.3 Route the three bounded mechanical cases through existing safe lock recovery and `NativeOrchestrationCoordinator` claim/recovery checks; replace unrestricted worktree reset with exact Verify-output attribution and fail-closed preservation of uncertain files/evidence.
- [x] 2.4 Add focused regression tests for threshold detection, proven-absent child process, orphan lock ownership, exact-candidate recovery, one-attempt idempotency, ambiguous evidence, and existing human-gate escalation.

## 3. Operator surfaces and telemetry

- [x] 3.1 Add the global Watchdog controls to provider/model administration with server-confirmed values, validation errors, and no hardcoded provider list; show the transversal union of enabled/available registry models and global stage-selectable Codex/Antigravity models, independent of the focused project.
- [x] 3.2 Add the authenticated `/mejora-continua` feed with project/status filters, observed recurrence summaries, copy-as-draft, discard, and no GitHub mutation.
- [x] 3.3 Extend `Diagnóstico & Supervisión` with run-scoped activity, elapsed stage time, persisted Watchdog timeline, improvement-feed navigation, and truthful manual-diagnosis request states.
- [x] 3.4 Change the autonomy series to the observed completed-run share without operator intervention; preserve active machine-time semantics and explicit no-data for incomplete/ambiguous histories.
- [x] 3.5 Add focused Playwright E2E coverage for settings persistence, feed filtering/copy/discard, Trabajo Actual diagnostics, and the rendered autonomy no-data/aggregate states.

## 4. Integration evidence

- [x] 4.1 Run the focused backend, PostgreSQL integration, and frontend checks for the changed areas; record command results and observed database/API/UI effects against the same candidate.
- [ ] 4.2 [DEFERRED] After deployment, verify a real Watchdog-triggered recovery and a fail-closed escalation through the existing orchestrator/recovery path, with persisted event and candidate-bound evidence; do not substitute mocked calls for this integration proof. Preserve the current candidate and run; defer this proof until the deployed version can be exercised end to end.
