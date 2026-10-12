## Design

### Confinement session

Use one shared `AgentProcessConfinement` session builder for implementer and reviewer subprocesses. Before launch it validates the assigned worktree and runtime roots, creates an attempt-unique mode-0700 state directory outside the worktree, and exposes only narrowly bound private directories for Codex/XDG state and temporary files. Bubblewrap keeps the host root read-only, binds the assigned worktree read-write, and binds the private per-attempt runtime writable; the runtime installation, managed checkout, other worktrees, global home, global `.codex`, and host `/tmp` remain read-only. Environment variables point only to the private paths. Session cleanup is tied to the full child-process lifetime and is run after normal exit, timeout, cancellation, or launch failure. The macOS sandbox path remains fail-closed and may use the same private runtime layout without claiming Linux/Bubblewrap validation.

Checks do not inherit agent state or Codex credentials; they receive only the existing check-specific command environment and their own minimal temporary storage if required.

### Credential projection

Resolve the existing Codex credential source from the effective `CODEX_HOME`, or the effective service HOME plus `.codex` when unset. Validate a regular, non-symlink source file and private permissions, then copy only `auth.json` into the attempt-private Codex home with mode 0600. Never bind the persistent `.codex` directory writable and never return credential contents in diagnostics. The child may update only its private copy. Compare credential state before and after execution without logging either value. Because a process running model-authored code cannot be trusted to author a replacement persistent bearer credential, changed auth state is not copied back; mark the execution explicitly as an environment/authentication continuation blocker and do not silently treat it as a successful reusable credential. Cleanup removes the private copy after the child is reaped. If the existing deployment has no authorized mechanism to persist a required rotation, that limitation remains a fail-closed blocker rather than introducing a new auth authority.

### Outcome classification

Add narrow deterministic recognition for local sandbox initialization evidence (`EROFS`, missing required private HOME/TMP/XDG path, and known Codex state-runtime initialization errors). Apply quota, rate-limit, authentication, and policy classification first. Do not map generic `UNKNOWN_ERROR` to environment failure. The normalized environment result must flow into continuation governance and attempt evidence without provider health degradation, corrective retry consumption, or executor reassignment.

### Durable continuation

Use the existing `ControlPlaneService.CONTINUE` command and its optimistic concurrency/action audit. It reuses the same Run ID and linked Job ID. When a durable worktree record is `DELETED` and its exact path is absent, WorktreeManager may transition through its existing pending-ownership/create protocol only after proving project/repository binding, run/job/change identity, persisted recovery branch, branch commit ancestry/base identity, expected ownership marker fields and published OpenSpec handoff identity. Before recreating the workspace it observes the bound remote base ref through the existing GitHub App Git authority and requires that SHA to match the persisted source base and local base. It must not adopt an arbitrary directory, silently change a contradictory branch/base, create another Run/Job/saga, or rely on direct database mutation. If ownership, branch identity, base advancement, or integration policy evidence is ambiguous, continuation fails closed. The prior attempt and all historical evidence remain intact.

### Validation

Pure/unit tests exercise mount construction and cleanup. Linux-only integration tests with real Bubblewrap prove permitted and denied writes and execute a real Codex CLI `app-server` initialize handshake without a turn request; network is unshared when initialization permits. If the handshake cannot complete without network, isolation success and handshake limitation are reported separately. PostgreSQL integration tests exercise the canonical CONTINUE path and deleted-worktree recreation with real persistence/repository/Git components while the runner is a no-inference deterministic command.
