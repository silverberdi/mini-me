## 1. Bubblewrap temporary runtime

- [x] 1.1 Add an invocation-private `--tmpfs /tmp` to the existing Linux Bubblewrap command after the `/dev` mapping, preserving read-only host mounts and worktree-only persistent writes.
- [x] 1.2 Set `DOTNET_CLI_DO_NOT_USE_MSBUILD_SERVER=1` in the existing confined child-process environment without changing machine-wide or unrelated provider configuration.
- [x] 1.3 Add a real Linux Bubblewrap test proving `/tmp` is writable within one invocation, does not alter host `/tmp`, is not shared with a second invocation, and disappears after exit; retain negative checks for persistent writes outside the worktree.

## 2. Fenced recovery after restart

- [x] 2.1 Update stage recovery classification so a prior boot on the same host proves recorded processes are gone, while same-boot recovery still requires coordinator, workflow process, and process-group absence; preserve fail-closed behavior for unknown or contradictory evidence.
- [x] 2.2 Add PostgreSQL integration coverage for an expired incomplete invocation from a prior boot: verify one durable `STAGE_INVOCATION_ABANDONED` event, a higher-fence successor claim for the same candidate/stage, and rejection of stale-worker mutations.
- [x] 2.3 Add recovery regression coverage proving live/unknown process identity and candidate/stage mismatches do not abandon or redispatch the invocation.

## 3. Verification

- [x] 3.1 Run the focused confinement and orchestration recovery tests, including the Linux Bubblewrap and disposable PostgreSQL integration paths, then run strict OpenSpec validation for this Change.
