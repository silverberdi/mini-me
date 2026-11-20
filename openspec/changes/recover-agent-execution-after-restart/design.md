## Context

See `proposal.md` and the two delta specs. Linux Bubblewrap already exposes a virtual `/dev`, but the command does not mount a writable `/tmp`. Stage invocation events and fenced PostgreSQL claims already exist; `_stage_recovery_is_safe` currently rejects a coordinator identity whose `boot_id` differs from the current boot, even though process identity classification can prove that identity is gone.

## Goals / Non-Goals

**Goals:** Satisfy the sandbox's ordinary temporary-file/IPC needs without exposing host temporary storage, stop build daemons from outliving their confined invocation, and recover only provably dead invocations under the same candidate and a newer fenced claim.

**Non-Goals:** Change the worktree write boundary, weaken unknown/live process handling, add recovery tables or background monitors, replay external work whose result is ambiguous, or deploy/restart production services as part of this Change.

## Decisions

1. **Mount invocation-private `/tmp` in the existing Linux Bubblewrap command.** Add `--tmpfs /tmp` immediately after the existing `--dev /dev` mapping. This lets runtime IPC and build tools use standard temporary paths while keeping host `/tmp` inaccessible and the temporary contents nonpersistent. Reject binding host `/tmp`, adding a shared runtime temp directory, or broadening worktree writes because each weakens isolation or adds state.

2. **Set the MSBuild server opt-out in the existing child-process environment.** Add `DOTNET_CLI_DO_NOT_USE_MSBUILD_SERVER=1` where the confined executor assembles environment variables, so the setting applies to the process tree and is not a machine-wide service setting. Do not add a general daemon-management subsystem; other tools remain governed by their existing process lifetime and confinement.

3. **Treat a changed boot identity as proof of process death only for complete, same-host evidence.** For an incomplete invocation, require the existing expired-claim condition, exact candidate/stage match, and recorded coordinator and workflow identities with known host and boot IDs. If both identities belong to the same host and a previous boot, that boot transition proves their processes and process group cannot still exist. In the same boot, continue to require explicit `GONE` results for the coordinator, workflow process, and process group. Missing, contradictory, live, cross-host, or otherwise unknown evidence remains blocked. This addresses the current same-boot equality check without relaxing fail-closed recovery.

4. **Use the existing journal and fenced claim transition.** The current `orchestration_stage_events` and claim repository remain the sole durable mechanism. After proof and validation, atomically reacquire the expired claim with a higher fence, append one `STAGE_INVOCATION_ABANDONED` event with the observed reason, and append the new started event for the same candidate/stage. Do not release then reacquire in separate operations, which would open a race for another worker; the fenced reacquisition replaces the expired ownership. No schema migration is expected.

5. **Verify with the existing real boundaries.** Keep unit assertions for command/environment construction, add a real Linux Bubblewrap check that temporary writes stay inside a single invocation, and exercise restart recovery against disposable PostgreSQL with prior-boot evidence. Do not treat mocked identity checks alone as proof of the database transition.

## Risks / Trade-offs

- **[Risk] A same-host boot ID could be missing or malformed.** → Keep recovery blocked unless both persisted identities and the current host can be compared unambiguously.
- **[Risk] PID or process-group identifiers may be reused within one boot.** → Continue validating process start markers and require the process group to be absent when recovery relies on same-boot evidence.
- **[Risk] Temporary files could be mistaken for candidate output.** → Keep `/tmp` ephemeral and separate from the worktree; assert host `/tmp` is unchanged and temporary contents disappear after invocation.
- **[Risk] The prior experimental PR #449 exercised only the `/tmp` portion and was closed unmerged.** → Build evidence from the current branch's real Linux and PostgreSQL tests; do not carry over its test report as verification.
