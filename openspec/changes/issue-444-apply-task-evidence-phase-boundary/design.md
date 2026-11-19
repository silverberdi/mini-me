## Context

See `proposal.md` for the failure being corrected. On current `main`, `_run_apply` tells the implementer to leave a task unchecked when published evidence does not match the candidate SHA; `_apply_recovery_context` separately instructs it to check tasks from observed diff and passing relevant tests. The canonical `minime-implementer` skill asks for diff and tests but does not explain that candidate SHA is created/confirmed after Apply. The current task-tracking spec requires coordinator verification of task claims, while candidate identity and published-version evidence are already governed by existing fail-closed checks.

## Goals / Non-Goals

**Goals:**

- Make normal and recovery Apply guidance consistent about when task checkboxes can be completed.
- Keep task progress evidence tied to the active worktree and passing relevant tests.
- Permit checksum-verified external immutable assets and intentionally untracked fixtures without fabricating Git provenance.
- Preserve candidate-SHA checks at Verify/review and for evidence claiming that a published version is the current candidate.

**Non-Goals:**

- Changing OpenSpec CLI behavior or implementing an OpenSpec workflow in mini me.
- Changing Verify, independent review, candidate identity, retry policy, persistence, or completion authority.
- Adding a database field/table, wrapper, custom validator, deployment step, or test framework.

## Decisions

1. **Treat Apply checkboxes as implementation progress, not a candidate attestation.** Update the canonical implementer skill, `_run_apply`, and `_apply_recovery_context` to tell the executor to run relevant local automated tests and use the visible worktree diff before marking an implementation task complete. A final coordinator-issued candidate SHA is not a prerequisite for that checkbox. The coordinator's current post-invocation checks still determine whether the work advances.

2. **Keep the SHA rule specific to evidence that identifies a candidate.** Do not remove or weaken the existing exact-SHA check for claims that a published build/version is the current candidate. For an external immutable asset or ignored fixture, use a deterministic SHA-256 check plus relevant local test results as evidence for the asset; the check does not replace evidence for tracked code or candidate identity.

3. **Reuse current checks and test conventions.** Inspect the existing task completion and published-evidence checks before changing behavior. Modify only a check if it currently blocks the above allowed Apply evidence; do not add a parallel evidence engine. Add focused regression tests proving normal and recovery instructions have the same phase boundary, and that coordinator checks still reject unsupported task completions and mismatched candidate-specific evidence.

4. **Keep scope to Issue #444.** Changes are limited to the implementer skill, Apply prompts, and focused tests/spec for task completion evidence. No schema/database migration is expected.

## Risks / Trade-offs

- [Risk] Relaxing the wording could be misread as allowing unchecked or unsupported work to count as done → [Mitigation] Require corresponding worktree diff and passing relevant tests, retain coordinator-observed checks, and explicitly preserve fail-closed candidate-SHA verification.
- [Risk] A checksum alone can identify bytes without proving that an asset is trustworthy → [Mitigation] Use only the expected digest specified by the approved Change or trusted source; this Issue does not authorize new sources or asset acquisition.
