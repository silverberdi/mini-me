# Proposal: Local Worker Code Edit Execution

## Why
The minimal local worker (`minime.local_worker`) can evaluate task eligibility and generate structured JSON responses from Ollama, but it cannot apply code patches to authorized execution worktrees. Extending the local worker to safely parse, validate, and apply bounded code edits inside an authorized `EXECUTION_WORKTREE` enables offline, low-cost execution of LOW-risk tasks (`SMALL_CODE_FIX`, `TEST_AUTHORING`, etc.) while strictly maintaining Stage C workspace isolation and SDLC guardrails.

## What Changes
- Add patch contract fields to `LocalWorkerResult` (`patch: str | None`, `next_action: str | None`).
- Add deterministic patch policy validation (`validate_patch_policy`) ensuring patches touch only `allowed_files`, contain no path traversal or absolute paths, and do not target runtime checkout or managed repository directly.
- Add `LocalPatchApplier` to safely apply validated diffs inside authorized `EXECUTION_WORKTREE` instances via `git apply` after verifying `ManagedWorkspaceGuard` authorization and `WorktreeManager` ownership.
- Extend `LocalWorkerService` flow to handle patch validation, authorized application, post-apply changed-file verification, clean re-baselining prior to a single corrective attempt, and enriched `LocalExecutionEvidence`.
- Keep local Qwen strictly implement-only (zero review, audit, approve, or merge authority).
