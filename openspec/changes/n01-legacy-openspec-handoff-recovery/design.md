## Context

See `proposal.md` for the incident. PR #145 permits descendant main advancement while preserving source base B, but a recreated recovery snapshot may have OpenSpec bytes that differ from the authoritative published commit by exactly one omitted final LF. After this materialization error, ownership is already `CREATED`, so retry must validate the existing canonical Git worktree rather than treating it as an arbitrary workspace or comparing its historical B lineage with current main C.

## Goals / Non-Goals

**Goals:** validate all artifact and ownership evidence before repair; permit a narrowly defined, idempotent LF-only reconciliation; adopt the same CREATED recovery worktree; preserve B and the original snapshot commit; durably record repair identities; keep all other differences fail-closed.

**Non-Goals:** changing the recovery branch/snapshot, rebasing/resetting to C, producing a candidate, rerunning admission, changing provider/sandbox policy, or modifying production.

## Decisions

- Reuse the existing published-ref authority: verify exact binding, `published_ref`, persisted SHA and remote `ls-remote`; fetch and verify the exact commit before reading blobs. The Git object tree is the sole byte authority.
- Validate the manifest as the exact permitted OpenSpec layout, with required proposal/tasks/design and one or more spec Markdown files; reject symlinks, missing/extra paths, and non-regular entries.
- For every file, accept only byte equality or (when the published blob ends in LF) exact equality with `blob[:-1]`. Complete validation for all files before writing any. Then atomically replace only differing files with their exact published blob bytes. Repeated calls accept already repaired files and do not rewrite them.
- Enable the repair only after canonical recovery lineage validation: durable CREATED/DELETED ownership identity, valid project binding and marker, registered worktree path when CREATED, exact persisted branch and snapshot commit/event, no candidate SHA, and authenticated remote base observation proving original B and local base are ancestors of stable remote C.
- Factor recovery validation so both absent DELETED recreation and existing CREATED adoption use the same branch/snapshot/base proofs. For CREATED, verify that the physical path is the Git-registered worktree and its HEAD is the preserved snapshot; do not run generic adoption against C as the source base.
- Persist a dedicated event containing project/change/run/job, worktree ownership ID, B, published ref/SHA, snapshot SHA and sorted repaired paths with before/after content digests. Never persist artifact contents or credentials. Event persistence is idempotent by checking for an existing event with the same immutable repair identity; the filesystem operation itself is safe to retry after interruption.
- Do not mark new code as a candidate. Keep WorktreeInfo and durable ownership base at B; do not move refs or alter the snapshot branch.

## Risks / Trade-offs

- A crash can occur between individual file replacements; retry validates every remaining file against the same exact two accepted forms, then completes safely. Arbitrary partial or unrelated edits remain blocked.
- Git publication observation may be unavailable; the repair and continuation then fail closed without changing files.
- Durable event writes and local file replacement cannot be one ACID transaction; idempotent postcondition observation makes retry safe without changing broader persistence architecture.
