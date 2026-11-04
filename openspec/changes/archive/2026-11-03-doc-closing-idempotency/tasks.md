## 1. Observe and resume DOC_CLOSING state

- [x] 1.1 Add a read-only observation for the documentation worktree that identifies an active Change versus one unique archived Change and verifies the archive artifacts and corresponding main-spec outputs required by the design.
- [x] 1.2 Skip native Sync and Archive when the observed archived/synchronized state is complete, then continue through the existing PR2 preparation, creation, and remote identity verification path.
- [x] 1.3 Preserve native Sync followed by Archive for an active Change; keep ambiguous or incomplete archived state paused with the documentation worktree preserved and a diagnostic rather than treating it as completed.

## 2. Verify idempotent documentation closure

- [x] 2.1 Add focused coordinator tests proving active Changes use native Sync/Archive, completed archived state skips both dispatches and reaches PR2, and incomplete or duplicate archive evidence does not falsely pass.
- [ ] 2.2 Add an E2E against an authorized isolated GitHub fixture: seed completed state through native OpenSpec Sync/Archive, re-enter DOC_CLOSING, and verify the PR2 is created and bound to the documentation candidate without another Sync/Archive invocation.
