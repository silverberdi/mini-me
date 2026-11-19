## Why

Apply instructions currently tie task completion to an exact candidate SHA even though the coordinator consolidates and identifies the candidate after the agent invocation. This can leave completed implementation work unchecked, consume recovery attempts, and send an avoidable human gate; the same guidance can demand Git provenance for external assets whose deterministic checksum and local tests are the relevant evidence.

## What Changes

- Define `tasks.md` checkboxes during Apply as implementation progress: mark an implementation task complete when its work is present in the active worktree and relevant automated tests pass, without waiting for the final candidate commit SHA.
- Clarify in the canonical `.agents/skills` implementer skill, its provisioned `.agent/skills` copy, and both normal and recovery Apply instructions that candidate SHA is established by coordination and is used by Verify and independent review for candidate identity, not as a prerequisite for Apply task checkboxes.
- Accept deterministic SHA-256 verification plus passing local tests for external immutable assets and intentionally untracked fixtures; do not require a Git commit for files that are intentionally outside Git.
- Preserve coordinator-observed diff/test checks, fail-closed completion and regression handling, and candidate-SHA validation for candidate-specific or published-version evidence.
- Add focused regression coverage for normal Apply instructions, recovery instructions, and the existing task/evidence checks. Do not add persistence, wrappers, or parallel OpenSpec validation.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `openspec-task-tracking`: Define when an Apply task checkbox may be completed and keep that progress distinct from candidate verification and stage completion.

## Impact

- Source: GitHub Issue [#444](https://github.com/silverberdi/mini-me/issues/444).
- `src/minime/services/orchestration_coordinator.py`: `_run_apply` prompt and `_apply_recovery_context` guidance.
- `.agents/skills/minime-implementer/SKILL.md`: canonical skill source; `.agent/skills/minime-implementer/SKILL.md`: mirrored copy provisioned for Antigravity.
- Focused Apply/task-tracking tests and the existing `openspec-task-tracking` capability.
- No API, schema, database, dependency, deployment, or OpenSpec CLI changes.
