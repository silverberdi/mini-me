## Context

See `proposal.md` and the three delta specs. The coordinator currently computes the stage candidate fingerprint before it examines an incomplete invocation. A dirty DOC_CLOSING worktree therefore no longer matches the persisted claim key. `WorktreeManager.create_worktree` currently creates Git worktrees without reusing the base repository's installed Node dependencies. The Playwright reset helper currently resumes the project through the API and suppresses failures; it does not clear residual runs first.

The current root `.gitignore` already contains `node_modules/`, covering root and nested dependency paths for this repository. The Playwright server configuration has both `MINIME_DATABASE_URL` and `MINIME_TEST_DATABASE_URL` inputs, so E2E reset must positively target the disposable test database before it can mutate state.

## Goals / Non-Goals

**Goals:**

- Recover only a proven-abandoned DOC_CLOSING invocation on its exact still-owned worktree, while preserving the existing claim lease and fencing contract.
- Make locally installed Node dependencies available in matching new worktrees without network access or tracked dependency artifacts.
- Make the project lifecycle E2E setup deterministic, test-database-only, and failure-visible.

**Non-Goals:**

- Changing claim keys, lease durations, fencing tokens, process-confinement rules, human gates, or cancellation policy.
- Resetting worktrees for stages other than DOC_CLOSING, or replacing candidate worktrees with a different branch or commit.
- Adding a production endpoint, general-purpose test framework, dependency installer, or production project reset behavior.
- Requiring unrelated Playwright specs or a full repository suite as the verification gate for this focused change.

## Decisions

### Recover by the persisted invocation before hashing the dirty tree

Documentation worktrees must have durable ownership in the existing `orchestration_worktree_ownerships` registry before they are created or reused. Record the project, run, Change, canonical path, source repository identity, base SHA, branch, and ownership state through the existing ownership lifecycle; do not add a table or migration. Reuse requires an exact match across that record and the requested run/worktree identity. For a pre-existing documentation worktree with no ownership record, adopt it only when an incomplete `SYNC` or `ARCHIVE` invocation event recorded while the Run was in `DOC_CLOSING` identifies the same run, canonical path, branch, generation, and `HEAD`, and Git confirms that exact path is a worktree of the registered repository. Persist the ownership before any cleanup. If those facts are absent or disagree, fail closed and preserve the directory.

For `SYNC` or `ARCHIVE` while the Run is in `DOC_CLOSING`, locate the incomplete invocation from durable run/stage events and its persisted worktree identity before computing a fresh fingerprint. Verify the exact managed-worktree ownership, matching run, stage, branch, generation and `HEAD` SHA, and prove the previous coordinator and workflow process group are absent. Require the existing durable claim to be inactive/expired and acquire its successor through the existing fenced claim repository. A dead process is evidence for abandonment; it is not permission to bypass an active lease.

Acquire the claim in a short PostgreSQL transaction, then release database locks before filesystem work. Under that claim, use the managed-workspace guard to run `git reset --hard HEAD` followed by `git clean -fd` in the exact documentation worktree. Do not use `git clean -x`; ignored dependencies and local tool caches must remain. Recompute candidate identity only after both Git commands succeed. If cleanup fails, do not dispatch; release or let the claim expire through the current claim mechanism and report the failure so a later scheduler cycle can retry safely. If the process crashes during cleanup, the successor lease expires and a later cycle repeats the idempotent cleanup.

Commit the successor claim acquisition before filesystem work so its row lock is not held while Git runs. After cleanup, validate that persisted fence and save the old invocation's `STAGE_INVOCATION_ABANDONED` event and the successor `STAGE_INVOCATION_STARTED` event together in one PostgreSQL commit. This keeps audit records atomic without holding a database transaction across Git subprocesses. Preserve the existing claim format and one-recovery limit. The ownership record must continue to identify the same run and worktree through recovery; do not make a new path or branch to work around dirty state.

If the abandoned operation is `ARCHIVE`, the reset also removes any uncommitted main-spec changes previously produced by a completed `SYNC`. Record on the abandonment evidence that the reset occurred. On the next DOC_CLOSING pass, replay the native `SYNC` once for that same Change and worktree before invoking `ARCHIVE`; do not treat an earlier SYNC completion as satisfying this replay. After the replay has a completed invocation with its existing sync postcondition verified, the normal archive flow may use `--skip-specs`. A recovery from an abandoned `SYNC` already resumes through the normal SYNC-then-ARCHIVE sequence. This remains a replay of the existing native operation, not a second workflow or a new recovery state.

Alternatives rejected: computing a new fingerprint first (it loses the association with the interrupted invocation); cleaning before claiming (two scheduler processes could mutate the same worktree); holding a row lock across `git` (unnecessarily couples database availability to filesystem work); trusting a path or branch without durable run ownership; and changing claim semantics or adding a new recovery state/table.

### Link only dependencies that already exist and are covered by Git ignore

During new worktree creation, inspect the root and `frontend/` package manifests independently. For each matching package path, link its `node_modules` only when a valid installed directory exists at the same path in the registered base repository. Do not run npm, pnpm, or other network installation. Do not replace an existing target or follow a source path outside the registered repository. Confirm the resulting dependency path is ignored by Git before returning the worktree; the existing `node_modules/` ignore rule covers this repository. If the ignore check fails, stop with a diagnostic before dispatch rather than risk adding dependencies to the candidate.

Alternatives rejected: copying large dependency trees (slow and wasteful), network installation on each worktree (non-deterministic and requires network), and disabling Git safety checks or adding ignore rules dynamically during candidate creation (creates unrequested project diffs).

### Reset only the designated E2E project through existing test-time APIs

Keep cleanup in the Playwright test helper and use existing run-list and run-cancellation APIs against the configured disposable E2E database; do not add a production reset endpoint or direct production-database writer. Restrict selection to active runs for `e2e-project`. Cancel only runs eligible under the existing cancellation service. If an active job or other state prevents safe cancellation, fail setup with the run identity and cause; do not mark a live job inactive behind the coordinator. Resume the project only after cleanup succeeds. The Playwright server must use the explicitly configured test database and fail before tests if its database identity is not the declared E2E database.

Do not catch and downgrade setup/teardown failures to warnings. Keep E2E proof to `project-pause-resume.spec.ts` plus any other spec that directly uses `resetProjectState` (`error-feedback.spec.ts`); these are the consumers affected by the helper change.

Alternatives rejected: directly editing production endpoints, silently mutating run rows around lifecycle authority, or keeping the current warning-only cleanup that reports false success.

## Risks / Trade-offs

- **A reset can discard uncommitted DOC_CLOSING artifacts.** Restrict it to the exact durably owned worktree after the previous process group is proven absent and the durable claim is replaceable; retain the prior attempt event and base commit evidence. Legacy worktrees without sufficient invocation evidence remain untouched.
- **A second scheduler may race recovery.** Acquire the existing fenced claim before changing files and revalidate the fence before committing invocation events.
- **Dependency links can expose an invalid or stale install.** Link only an existing matching package directory; do not fetch or mutate dependencies, and keep the E2E/build checks as the final validity signal.
- **The E2E database may be misconfigured.** Require an explicit test database identity and abort before cleanup when it does not match.
- **A test run may contain a live stage job.** Do not force cancellation; fail setup visibly and leave the run intact for diagnosis.

## Migration Plan

No database schema migration is expected. The change uses existing worktree ownership, stage invocation events, recovery claims, run cancellation, and Playwright configuration. Rollback is a code revert; no production data or project state is changed by deployment. The only destructive file operation is confined to the exact managed DOC_CLOSING worktree after recovery proof and claim acquisition.

## Open Questions

None. If dependency files are absent/invalid, cleanup cannot prove worktree ownership, the process is not conclusively gone, the claim is still active, or the E2E database identity is unverified, the safe behavior is to stop and report the evidence.
