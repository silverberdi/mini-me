## Context

See `proposal.md` for the failure and scope. The current DOC_CLOSING path reuses its documentation worktree, but calls `_run_sync_and_archive` whenever no PR2 number is stored. That helper dispatches Sync before checking for an archived Change, then verifies the archive only after both native workflows return. A re-entry after a successful archive therefore invokes Sync against a Change that has left `openspec/changes/`.

The existing flow already preserves the documentation worktree and advances to the established PR2 preparation/creation path after `_run_sync_and_archive` succeeds. The change should add state observation at this boundary and retain agent-owned OpenSpec workflows for unfinished work.

## Goals / Non-Goals

**Goals:**

- Observe the documentation candidate before dispatching native Sync or Archive on DOC_CLOSING re-entry.
- Recognize the already archived and synchronized state and continue to PR2 preparation/creation without invoking either workflow again.
- Keep the existing native Sync → Archive path for an active Change and keep ambiguous/incomplete state fail-closed.

**Non-Goals:**

- Changing any stage outside DOC_CLOSING or the existing documentation PR path.
- Reimplementing OpenSpec sync/archive, adding a second semantic spec merger/verifier, or adding database state.
- Changing PR merge or issue closure policy.

## Decisions

### Observe candidate OpenSpec state before dispatch

Add a narrow read-only state probe at the DOC_CLOSING boundary, before `_run_sync_and_archive` resolves or invokes agent workflows. It inspects the existing documentation worktree for the active Change and a unique matching archived Change (including the existing date-prefixed archive naming convention). It requires the archived Change to contain the existing required artifacts and its declared delta spec paths to resolve to the corresponding main specs under `openspec/specs/`.

Treat the archive plus corresponding main-spec outputs in the same documentation candidate as the durable result of the already-successful native Sync/Archive sequence. The probe only establishes this observable completed state; native workflows remain the sole owners of spec merging and archive operations. If this completed state is present, return success from the DOC_CLOSING sync/archive gate without resolving or dispatching Sync/Archive. The existing PR2 logic then prepares, opens, and verifies the documentation PR.

If the Change remains active and no matching archive exists, preserve the existing native Sync → Archive workflow. If archive evidence is duplicated, incomplete, or lacks corresponding main-spec outputs, do not classify it as complete or retry Sync against a missing active Change; preserve the worktree and return a diagnostic paused result for that inconsistent state.

### Keep the existing downstream PR2 continuation

The observation result is consumed only where the current flow decides whether to call `_run_sync_and_archive`. A verified completed state follows the same code that obtains the documentation candidate SHA and prepares/creates PR2. Existing durable PR2 identity checks continue to prevent duplicate PR creation on later re-entry.

Alternative considered: run Sync and Archive on every attempt and interpret `change not found` as success. Rejected because the error alone does not prove the Change is archived or that its specs are synchronized. A new database marker is also unnecessary because the candidate already contains durable OpenSpec/Git evidence.

## Risks / Trade-offs

- [An archived Change may exist without all main-spec outputs] → Require the complete archive artifact set and corresponding main-spec paths before treating the work as done; otherwise pause with the worktree preserved.
- [A same-named unrelated archive could be mistaken for this Change] → Require exactly one match using the existing exact-name/date-suffix rule and inspect the archive contents in the bound documentation worktree.
- [State may change between observation and PR creation] → Continue using the existing candidate identity and remote PR confirmation checks; do not create a new worktree or bypass PR verification.

## Migration Plan

No database migration is needed. Existing active DOC_CLOSING runs keep using native Sync/Archive. Existing documentation candidates with completed archive/spec state become resumable directly into the current PR2 path. Rollback is a code rollback; already committed documentation candidates remain inspectable and are not rewritten.
