## Purpose

Allows an already-owned historical execution worktree to continue safely when its OpenSpec snapshot differs from the authoritative publication only by one omitted final LF, without changing the original recovery lineage.

## ADDED Requirements

### Requirement: Published OpenSpec LF-only Recovery
The system MUST repair a historical recovery worktree only when its project, change, Run, Job, ownership, repository binding, branch, snapshot event, publication identity, and original source base are durably consistent; no implementation candidate exists; and the remote base is a stable descendant of the original source base. The published Git commit tree MUST define the exact allowed manifest and bytes. For every manifest file, the existing worktree content MUST either equal the published blob exactly or equal that blob with exactly one final LF omitted, and every file MUST be checked before any repair write. The system MUST restore only the exact published bytes, preserve the recovery snapshot and source base, and durably record the repair identity without persisting file contents or secrets. Any other difference MUST fail closed.

#### Scenario: Repair exact missing final LF in a verified recovery worktree
- **GIVEN** a canonical recovery worktree with verified ownership, marker, snapshot event, branch, Run/Job identity, and no candidate
- **AND** its exact published ref/SHA and artifact manifest are authoritatively verified
- **AND** every manifest file is either byte-identical to the published blob or differs only by one missing final LF
- **WHEN** canonical continuation materializes published OpenSpec artifacts
- **THEN** the system validates every path and file before writing
- **AND** restores only the exact published blob bytes for files missing that LF
- **AND** preserves the recovery branch, snapshot commit, and original base identity B
- **AND** records durable repair evidence with identities and content digests but no artifact contents

#### Scenario: Retry after interrupted or completed LF-only repair
- **GIVEN** the same authorized recovery worktree and publication identity
- **AND** a prior repair attempt may have replaced a subset of eligible files
- **WHEN** continuation repeats with the same Run/Job and publication identities
- **THEN** already restored files are accepted unchanged and remaining LF-only files are repaired
- **AND** no snapshot, branch, candidate, Run, Job, or admission identity is duplicated or rewritten

#### Scenario: Reject any discrepancy outside the exact LF-only form
- **GIVEN** any file has another byte difference, a different manifest, an extra or absent file, a symlink, an unobservable/contradictory remote publication, inconsistent ownership or snapshot evidence, an existing candidate, or a divergent base
- **WHEN** continuation attempts to adopt or materialize the worktree
- **THEN** the operation fails closed before repair writes
- **AND** preserves the worktree, snapshot, Run, Job, and existing evidence

### Requirement: Canonical Adoption of Created Recovery Worktree
The system MUST adopt an existing `CREATED` worktree for recovery continuation only when its exact derived path is registered by Git, the durable ownership and marker match the same project, Run, Job, change, repository and original base, and the recovery branch tip is the uniquely evidenced artifact-only snapshot rooted at that base. The original source base MUST remain the value reported by ownership, Run, Job and WorktreeInfo even when verified remote main has advanced to a descendant.

#### Scenario: Continue after materialization failed with ownership CREATED
- **GIVEN** the prior canonical CONTINUE reconstructed the exact recovery snapshot and set its ownership to CREATED before published-artifact materialization failed
- **AND** Git still registers the exact derived path and branch at the durable snapshot SHA
- **AND** all other repository, binding, marker, snapshot-event, no-candidate and stable B-to-C ancestry checks pass
- **WHEN** the same Run/Job is continued again with an authorized new action request
- **THEN** the manager adopts that same worktree, repairs only eligible LF omissions, and returns its original base B
- **AND** does not create a Run, Job, saga, snapshot commit, or new admission

#### Scenario: Reject an ordinary or arbitrarily occupied worktree as legacy recovery
- **GIVEN** a worktree lacks the exact durable recovery snapshot and event evidence, has a different Git identity/path/branch/HEAD, or is not a Git-registered canonical worktree
- **WHEN** canonical recovery adoption is attempted
- **THEN** adoption fails closed and does not modify its files or ownership
