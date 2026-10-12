## Why

On Ubuntu hosts whose `/etc/resolv.conf` resolves into `/run/systemd/resolve`, Bubblewrap's private `/run` masks the active resolver file and agent processes lose DNS. Projecting only the verified resolver file read-only restores name resolution without widening filesystem or network permissions.

## What Changes

- Project the verified host resolver file into the private Bubblewrap `/run` only when the configured resolver target would otherwise be hidden there.
- Preserve all existing worktree, ephemeral runtime, credential, and network namespace boundaries.
- Add Linux Bubblewrap regression coverage and document safe preconditions for a later continuation of an interrupted execution.

## Capabilities

### New Capabilities
- `bubblewrap-dns-resolution`: DNS configuration remains available to confined agent processes while `/run` stays private.

### Modified Capabilities

## Impact

Only `AgentProcessConfinement`, focused confinement tests, and this change's OpenSpec artifacts are affected. No provider, admission, scheduler, credential, or production state changes are included.
