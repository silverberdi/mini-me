# Design: Local Worker Code Edit Execution

## Architecture Decisions

### 1. Patch Parsing & Pre-Mutation Validation
Introduce patch validation functions in `minime.local_worker.patch_applier` (or `patch_policy` module):
- Parse unified diff headers (`--- a/path`, `+++ b/path`) to extract authoritative target files.
- Reject patches with absolute paths, directory traversal (`..`), symlinks, or forbidden file targets.
- Cross-check authoritative touched files $\subseteq$ `allowed_files`.

### 2. Isolation & SDLC Authority Integration
Patch application leverages existing Stage C SDLC isolation primitives:
- `ManagedWorkspaceGuard`: Ensures workspace role is strictly `EXECUTION_WORKTREE`.
- `WorktreeManager`: Validates durable worktree ownership before any filesystem operations.
- Direct writes or patch applications to `/opt/minime/app` (runtime checkout) or `/opt/minime/repos/mini-me` (managed repository) are strictly blocked.

### 3. Execution & Postcondition Check
- Invoke `git apply` via `subprocess.run` with `cwd=execution_worktree_path`, `check=False`, `capture_output=True`, `text=True`, and `timeout=30`.
- Verify `git diff --name-only` after application to ensure actual modified files $\subseteq$ `allowed_files`.

### 4. Single Corrective Attempt & Baseline Restoration
- If patch application or deterministic validation fails on attempt 1, the worktree is restored to a clean baseline (`git checkout .` / `git clean -fd` within the worktree) before attempting a second (and final) corrective model invocation.

### 5. Evidence Enrichment
- Extend `LocalExecutionEvidence` dataclass / model with fields for patch status (`patch_proposed`, `patch_applied`), authoritative changed files, and worktree identity.
