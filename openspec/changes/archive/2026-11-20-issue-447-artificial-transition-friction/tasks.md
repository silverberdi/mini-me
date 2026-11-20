## 1. Stage feasibility

- [x] 1.1 Change the stage-precondition check so an empty `evidence_refs` list alone does not block the transition; keep blockers for missing required capabilities and non-empty unknown or unverified references.
- [x] 1.2 Add focused regression tests for empty references proceeding without a gate and concrete unknown references remaining fail-closed.

## 2. Native Sync and Archive completion

- [x] 2.1 Remove mandatory completion-token reporting for Sync and Archive while preserving it for workflows that require it; continue parsing and routing a valid native `HUMAN_REQUIRED` handoff.
- [x] 2.2 Make Sync/Archive stage success independent of completion prose, but dependent on zero process exit, no timeout/preflight/environment error, and observable operation effects; keep Apply and Verify behavior unchanged.
- [x] 2.3 Pass the official `--yes --skip-specs` option to native Archive after Sync; verify the active Change is removed, exactly one complete archive exists, and synchronized main specs are present.
- [x] 2.4 Add regression coverage for token-free successful Sync/Archive, failed or effect-free operations, preserved human handoffs, and avoiding duplicate delta application.

## 3. DOC_CLOSING commit boundary

- [x] 3.1 Ensure DOC_CLOSING verifies and commits pending `openspec/` changes before PR2 progression both after a new archive and when re-entering with an already-complete archive.
- [x] 3.2 Keep unrelated staged files out of the OpenSpec commit, verify the resulting Git head and clean OpenSpec paths, and avoid empty commits when the archive is already committed.
- [x] 3.3 Add regression coverage for successful archive re-entry with pending OpenSpec changes, already-committed archive state, and unsafe/failed commit conditions.

## 4. End-to-end evidence

- [x] 4.1 Run OpenSpec validation for the Change and focused feasibility, runner, and DOC_CLOSING tests; record commands and results against the candidate SHA.
- [x] 4.2 Exercise the native Archive CLI with `--skip-specs` in an isolated temporary Git repository and verify the resulting archive and synchronized-spec state without mutating the operational repository.
- [x] 4.3 Run an authorized end-to-end DOC_CLOSING flow through the configured agent workflows and test persistence, Git commit, and transition evidence in an isolated test environment; do not use production issues, branches, or repositories.
