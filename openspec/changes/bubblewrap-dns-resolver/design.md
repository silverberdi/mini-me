## Context

The Bubblewrap profile exposes the host root read-only, then replaces `/run` with a private tmpfs and binds `/run/minime-agent` to the attempt-private writable state. On Ubuntu, `/etc/resolv.conf` may resolve to `/run/systemd/resolve/stub-resolv.conf`; that target disappears beneath the tmpfs, even though the original symlink remains visible.

## Decisions

- Resolve `/etc/resolv.conf` strictly on the host, verify the resolver link did not change during inspection, and require its effective target to be an existing readable regular file. Unverifiable or unsafe configurations fail closed.
- If the effective resolver path remains visible under the read-only host-root view, no additional mount is needed.
- If the resolver path would be hidden by private `/run`, create only the required parent directories in the private tmpfs and bind the verified file read-only at the resolver's effective path. Perform these operations after `--tmpfs /run` and before the private `/run/minime-agent` bind. Reject collision with the private agent runtime.
- Do not unshare networking except when the caller explicitly requests it. Do not expose any other host `/run` path or socket.
- The shared `AgentProcessConfinement` builder remains the sole mount authority for implementer and reviewer subprocesses.

## Recovery note

This change does not operate an existing Run or Job. Before a future continuation after an environment-only DNS failure, re-read the durable Run, linked Job, attempt history, candidate SHA, ownership/worktree state, claims, and pending external actions. Confirm the persisted repository/base identity and that no candidate or competing execution exists. Use the canonical Control Plane `CONTINUE` action with freshly observed optimistic-concurrency values and a new request ID; do not repeat `orchestrate start`, manually edit state, or assume prior attempt counts/statuses remain unchanged.

## Validation

Unit tests verify exact mount construction and fail-closed path handling. Linux integration tests use real Bubblewrap and the host resolver bytes in a `/run`-shaped isolated fixture to demonstrate the old missing-target behavior, read-only projection, effective DNS resolution, and continued isolation. Existing confinement, credential cleanup, and initialize-only tests remain in the focused regression set. The diagnostic does not launch a model turn.
