## 1. Reuse existing paths

- [x] 1.1 Inspect the current feasibility validator, gate response path, DOC_CLOSING archive workflow, installed OpenSpec CLI, and operator-action record; keep the implementation within these paths and remove only the superseded archive comparison/move instructions.

## 2. Correct and bound proposal feasibility

- [x] 2.1 Change Apply feasibility to require the verified configured execution profile and verified native Apply workflow without requiring a duplicate task-level `profile:execution` reference; preserve fail-closed behavior for missing or unknown capability evidence.
- [x] 2.2 Distinguish correctable report shape/mapping/stage diagnostics from actual missing evidence and execution failures using the existing validator; re-assess only correctable reports up to two corrective calls on the same candidate and evidence snapshot, preserving every attempt and stopping at the bound.
- [x] 2.3 Ensure every blocked feasibility gate retains agent guidance and includes the exact canonical native OpenSpec Update action; verify that selection updates and strictly validates the same Change without clearing blockers by text alone.
- [x] 2.4 Add positive and negative regression tests for workflow-only execution evidence, malformed stage/mapping correction, the two-retry ceiling, real evidence blockers, canonical Update selection, and no-progress/failure paths.

## 3. Make document archival use the native CLI

- [x] 3.1 Replace each provider-resolved Archive instruction entry point's free-text semantic comparison and manual directory movement with the installed `openspec archive -y <change-name>` command after Sync success is observed; retain fail-closed handling of unsuccessful CLI or ambiguous archive evidence.
- [x] 3.2 Exercise `openspec archive -y <change-name>` in an isolated temporary repository whose delta has already been synchronized; verify successful archive and preservation of the active Change when the CLI fails. Keep Sync on its installed native agent workflow and retain the existing DOC_CLOSING artifact observation for complete, incomplete, and ambiguous results.

## 4. Respond to the current gate through CLI safely

- [x] 4.1 Extract the existing web gate-response acceptance and idempotency behavior into one small shared operator-action operation; keep the web route behavior unchanged and reuse `OperatorActionRecord` without adding persistence tables.
- [x] 4.2 Add `--response` to `minime request run`, binding it to exactly one active Run and its current gate, using the shared operation, and rejecting missing, stale, or ambiguous targets before scheduling work.
- [x] 4.3 Add CLI/API integration tests for accepted responses, duplicate response idempotency, stale and absent gates, ambiguity, redaction, and prevention of duplicate dispatch or unauthorized transition.

## 5. Verify the complete Issue behavior

- [ ] 5.1 Run focused and adjacent tests, lint/type checks configured by the repository, strict OpenSpec validation, and `git diff --check` on the exact candidate SHA; document failures without weakening assertions.
- [ ] 5.2 Verify the changed boundaries with focused tests and only the real integrations they require: the configured thinking workflow for a correctable feasibility report, native OpenSpec Archive CLI on an isolated fixture after Sync, and CLI gate response through the existing durable operator-action path. Apply existing provider capacity and authorization rules; do not add a general per-step monitoring or evidence system.
- [x] 5.3 Re-run the affected regression checks after removing the superseded archive-skill comparison/move path; confirm the existing native workflows and gate safeguards remain authoritative.
