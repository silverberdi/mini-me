## 1. Recover abandoned DOC_CLOSING worktrees

- [x] 1.1 Persist documentation-worktree ownership in the existing registry before create/reuse, and safely adopt a legacy worktree only from matching incomplete SYNC/ARCHIVE invocation evidence recorded during DOC_CLOSING plus Git worktree identity; reject mismatches without modifying contents.
- [x] 1.2 Locate the incomplete SYNC/ARCHIVE invocation by its persisted run, DOC_CLOSING stage, durable worktree ownership, branch, generation, and HEAD before calculating a fresh dirty-tree fingerprint; preserve the existing process-proof, claim lease, fencing, and retry limits.
- [x] 1.3 Under the existing successor claim and managed-workspace guard, reset only the exact proven-abandoned documentation worktree to HEAD and clean untracked files without removing ignored dependencies; after an abandoned ARCHIVE reset, replay native SYNC and verify its effect before ARCHIVE; stop and report if ownership, process absence, claim eligibility, or Git cleanup cannot be verified.
- [x] 1.4 Recalculate the fingerprint after cleanup and atomically persist the abandoned and successor invocation events in PostgreSQL under the validated fence; add a focused PostgreSQL E2E covering ownership registration/adoption, dirty SYNC and ARCHIVE recovery (including sync replay after archive reset), event/claim evidence, and fail-closed cases against the disposable test database.

## 2. Reuse installed dependencies in new worktrees

- [x] 2.1 For matching root and `frontend/` package manifests, link only valid `node_modules` already installed at the corresponding registered-repository path; do not install packages or replace existing targets.
- [x] 2.2 Verify root and nested dependency links are ignored and absent from candidate Git status, index, and commit; retain the current repository's generic `node_modules/` ignore rule unless a focused test proves it insufficient.
- [x] 2.3 Add focused worktree tests for root and frontend dependencies, missing installs, and Git-ignore/index behavior.

## 3. Make project lifecycle E2E reset deterministic

- [x] 3.1 Restrict reset to `e2e-project` on the explicitly identified disposable E2E database; cancel only residual runs that the existing cancellation workflow can safely cancel, and surface any unsafe/live-job case without mutating it.
- [x] 3.2 Remove warning-only handling for reset failures and verify successful cleanup followed by immediate project pause/resume.
- [x] 3.3 Run the Playwright specs that consume `resetProjectState` (`project-pause-resume.spec.ts` and `error-feedback.spec.ts`) repeatedly against the E2E test server and record the database identity and results.
