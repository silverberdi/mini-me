# Spec: Managed Repository Runtime Isolation

## ADDED Requirements

### Requirement: Strict physical and logical separation of runtime checkout and managed repositories

The system SHALL enforce physical and logical path isolation between mini me's deployed runtime checkout (`RUNTIME`), managed project repository roots (`MANAGED_REPOSITORY`), and ephemeral execution worktrees (`EXECUTION_WORKTREE`), and Project OpenSpec Workspaces SHALL operate strictly as authorized logical subtrees located inside a `MANAGED_REPOSITORY` or `EXECUTION_WORKTREE`.

#### Scenario: Runtime checkout and managed repository root path collision denied
GIVEN a project registration or onboarding request specifying a managed repository path
WHEN the target path equals, contains, or is contained by the deployed RUNTIME checkout
THEN the system SHALL reject the path binding with outcome FAILURE
AND reason_code SHALL be POLICY_DENIED
AND SHALL NOT permit managed repository operations in the RUNTIME checkout.

#### Scenario: Mutating SDLC action against RUNTIME denied by ManagedWorkspaceGuard
GIVEN an active project job attempting a file write, git commit, branch operation, or OpenSpec mutation
WHEN the target path resolves inside the deployed RUNTIME checkout
THEN ManagedWorkspaceGuard SHALL deny the operation with outcome FAILURE
AND reason_code SHALL be POLICY_DENIED
AND the live RUNTIME process files SHALL remain untouched.

### Requirement: Process-level agent write confinement boundary

Every agent process executing in an `EXECUTION_WORKTREE` SHALL be executed within an OS/process-level write confinement boundary (e.g. sandbox write allow-lists, mount namespaces, or file permissions) restricting file write access strictly to the assigned worktree path.

#### Scenario: Agent attempts shell write into RUNTIME checkout
GIVEN an agent process executing inside an EXECUTION_WORKTREE
WHEN the process issues a shell or filesystem write command targeting RUNTIME (e.g. `cd /opt/minime/app && touch file`)
THEN the OS/process write confinement boundary SHALL block the syscall
AND the write SHALL fail with permission denied without altering RUNTIME.

#### Scenario: Agent attempts absolute path write outside worktree
GIVEN an agent process executing inside an EXECUTION_WORKTREE
WHEN the process attempts a file write targeting an absolute path outside its assigned worktree (e.g. `/etc/config` or `/tmp/payload`)
THEN the OS/process write confinement boundary SHALL block the write syscall
AND the write operation SHALL be DENIED.

#### Scenario: Agent attempts write through symlink pointing to RUNTIME
GIVEN an agent process executing inside an EXECUTION_WORKTREE
WHEN the process creates or traverses a symlink pointing from inside the worktree to a RUNTIME path
THEN the OS/process write confinement boundary SHALL resolve the realpath and block the write syscall
AND no RUNTIME file SHALL be modified.

### Requirement: Self-hosting isolation for mini me managing itself

When mini me executes SDLC tasks for its own repository (`mini-me`), the system SHALL maintain strict filesystem and repository distinction between the deployed runtime checkout and the managed project repository.

#### Scenario: Self-hosting mini me executes task in isolated managed worktree
GIVEN mini me executing a change for project identity "mini-me"
WHEN an implementer or reviewer agent receives work instructions
THEN the execution path SHALL resolve strictly under `<managed-root>/mini-me/worktrees/<run-id>`
AND file modifications SHALL NOT touch the live deployed RUNTIME checkout (e.g. `/opt/minime/app`)
AND equality of commit SHA or repository URL between RUNTIME and managed project SHALL NOT authorize RUNTIME workspace access.

### Requirement: Verified project managed-repository binding and remote identity

Every managed project SHALL maintain an authoritative, persisted `ProjectManagedRepositoryBinding` containing project identity, normalized `canonical_repository_identity`, `remote_name`, managed repository root path, worktree parent directory, and ownership metadata, and path guessing or `cwd` heuristics SHALL be strictly forbidden.

#### Scenario: Missing or unverified project binding blocks fresh work admission
GIVEN a project intake or readiness evaluation for a job
WHEN ProjectManagedRepositoryBinding is missing, unpersisted, or unverified
THEN the system SHALL block job admission with outcome UNKNOWN
AND reason_code SHALL be EVIDENCE_INSUFFICIENT
AND SHALL NOT infer managed paths from current working directory or folder name heuristics.

#### Scenario: Cross-project managed path access denied
GIVEN a job executing for project-A
WHEN a filesystem mutation or Git command targets a managed repository root bound to project-B
THEN ManagedWorkspaceGuard SHALL deny the operation with outcome FAILURE
AND reason_code SHALL be CONFLICT.

### Requirement: Central workspace mutation authorization guard

All SDLC filesystem edits, Git operations, worktree creation/deletion, and OpenSpec operations across mini me SHALL pass through a central `ManagedWorkspaceGuard` before execution.

#### Scenario: Workspace target outside trusted managed root denied
GIVEN a requested filesystem or Git mutation
WHEN target path canonicalization (resolving symlinks and relative segments) shows the path lies outside the configured trusted managed root
THEN ManagedWorkspaceGuard SHALL deny the operation with outcome FAILURE
AND reason_code SHALL be POLICY_DENIED.

#### Scenario: Symlink escape into RUNTIME denied
GIVEN a target path inside a managed repository or worktree containing a symlink pointing to a RUNTIME path
WHEN ManagedWorkspaceGuard canonicalizes the path using os.path.realpath
THEN the guard SHALL detect the RUNTIME collision and deny the mutation with outcome FAILURE
AND reason_code SHALL be POLICY_DENIED.

#### Scenario: Unknown workspace identity blocks mutation
GIVEN a mutation request for a path whose workspace role cannot be authoritatively established as MANAGED_REPOSITORY or EXECUTION_WORKTREE
THEN ManagedWorkspaceGuard SHALL return outcome UNKNOWN
AND reason_code SHALL be EVIDENCE_INSUFFICIENT
AND the mutation SHALL be strictly BLOCKED.

### Requirement: Fail-closed Git remote identity verification

Before permitting mutations in a managed repository or worktree, the system SHALL execute `git remote get-url <remote_name>` and compare normalized repository identity against `canonical_repository_identity`.

#### Scenario: Normalized Git remote identity mismatch blocks execution
GIVEN a managed repository path being verified by ManagedWorkspaceGuard
WHEN `git remote get-url <remote_name>` returns a remote URL whose normalized identity differs from `canonical_repository_identity`
THEN verification SHALL return outcome FAILURE
AND reason_code SHALL be CONFLICT
AND all mutating operations on that repository SHALL be BLOCKED.

#### Scenario: Unparseable Git remote returns UNKNOWN
GIVEN a managed repository path
WHEN remote query output is malformed, unparseable, or unobservable
THEN verification SHALL return outcome UNKNOWN
AND reason_code SHALL be UNOBSERVABLE
AND mutation SHALL be strictly BLOCKED.

### Requirement: Durable worktree ownership and 4-way reconciliation protocol

Authoritative worktree ownership SHALL be stored in durable database storage (`OrchestrationWorktreeOwnership`) outside the mutable worktree filesystem, and cleanup operations SHALL execute 4-way reconciliation (durable DB record, canonical path, Git `worktree list` observation, and in-tree marker if present).

#### Scenario: Ephemeral worktree created with durable DB ownership record
GIVEN a request to spawn an execution worktree for job J and run R
WHEN WorktreeManager creates the worktree under `<managed-root>/<project-id>/worktrees/<run-id>`
THEN it SHALL write a durable `OrchestrationWorktreeOwnership` record in DB with creation_state = "CREATED"
AND failure to persist or verify the durable DB record SHALL abort worktree initialization with outcome FAILURE and reason_code POSTCONDITION_NOT_PROVEN.

#### Scenario: In-tree marker alone without DB record cannot authorize deletion
GIVEN a cleanup task inspecting directory `<managed-root>/<project-id>/worktrees/unowned-folder`
WHEN `.minime-worktree.json` marker is present BUT no matching `OrchestrationWorktreeOwnership` DB record exists
THEN cleanup SHALL DENY deletion of the directory
AND SHALL return outcome UNKNOWN with reason_code EVIDENCE_INSUFFICIENT
AND SHALL preserve the directory for human operator review (`NEEDS_HUMAN`).

#### Scenario: Spoofed in-tree marker rejected during 4-way reconciliation
GIVEN a worktree directory containing a spoofed `.minime-worktree.json` file attempting to claim another project's job
WHEN cleanup reconciles the marker against durable DB records
THEN the mismatch SHALL be detected during 4-way reconciliation
AND deletion SHALL be DENIED with outcome FAILURE and reason_code CONFLICT.

### Requirement: Fail-closed partial worktree recovery protocol

Partial worktree recovery following process crash SHALL require an authoritative pre-creation durable DB record to authorize directory pruning.

#### Scenario: Partial worktree recovery authorized by durable pre-creation DB record
GIVEN a process crash during worktree creation leaving an incomplete worktree directory on disk
WHEN restart recovery finds a durable `OrchestrationWorktreeOwnership` record in DB with creation_state = "PENDING" matching the exact canonical path and job identity
THEN recovery MAY prune the partial worktree directory safely and re-initialize.

#### Scenario: Incomplete worktree directory lacking DB record preserved for operator
GIVEN an incomplete worktree directory on disk
WHEN no matching durable `OrchestrationWorktreeOwnership` DB record exists
THEN recovery SHALL NOT delete the directory
AND SHALL return outcome UNKNOWN with reason_code EVIDENCE_INSUFFICIENT
AND SHALL preserve the directory for operator review (`NEEDS_HUMAN`).

### Requirement: OpenSpec operations bound to managed repository paths

OpenSpec change authoring, canonical spec synchronization (`OpenSpecSyncService`), and change archiving (`OpenSpecArchiveService`) SHALL target project managed repository paths exclusively and SHALL NOT execute against RUNTIME checkout paths.

#### Scenario: OpenSpec sync targeted at RUNTIME path denied
GIVEN a request to sync OpenSpec delta specs
WHEN target specs directory path resolves to a RUNTIME checkout directory
THEN ManagedWorkspaceGuard SHALL intercept the invocation and return outcome FAILURE
AND reason_code SHALL be POLICY_DENIED
AND no files in the RUNTIME checkout SHALL be modified.

#### Scenario: OpenSpec sync and archive execute inside verified MANAGED_REPOSITORY
GIVEN an OpenSpec change ready for post-merge archive
WHEN OpenSpecArchiveService relocates the active change directory to `openspec/changes/archive/`
THEN the operation SHALL execute strictly within the verified `MANAGED_REPOSITORY` directory
AND canonical main spec updates SHALL be verified in the project's `openspec/specs/` directory before archive completion.

### Requirement: Formalized deployment authority boundary and runtime immutability

`ManagedWorkspaceGuard` SHALL DENY all SDLC mutations against RUNTIME, and deployment SHALL execute exclusively via a separate `DeploymentAuthority` boundary that does not grant managed workspace semantics to RUNTIME.

#### Scenario: Deployment authority updates RUNTIME without granting managed workspace role
GIVEN an explicit deployment process executing under DeploymentAuthority to promote a verified candidate commit SHA to RUNTIME
WHEN deployment completes successfully and service restarts
THEN RUNTIME SHA SHALL equal the candidate SHA
BUT RUNTIME workspace role SHALL remain strictly `RUNTIME` (read-only for SDLC)
AND ManagedWorkspaceGuard SHALL continue to DENY all SDLC mutations against RUNTIME (`POLICY_DENIED`).

#### Scenario: SDLC caller cannot impersonate deployment authority
GIVEN an orchestration driver, agent runner, or OpenSpec service executing SDLC tasks
WHEN the caller attempts to invoke or escalate into DeploymentAuthority to mutate RUNTIME
THEN the escalation attempt SHALL be blocked with outcome FAILURE
AND reason_code SHALL be POLICY_DENIED.

### Requirement: Legacy workspace aliasing detection and reconciliation

The system SHALL detect legacy installations where RUNTIME aliases the managed project checkout and SHALL block fresh work admission until separate managed repository isolation is established.

#### Scenario: Legacy aliased installation detected and admission blocked
GIVEN mini me starting up on an existing installation
WHEN readiness inspection detects that `managed_repository_root` overlaps with RUNTIME or lacks separate isolation
THEN the system SHALL flag legacy aliasing and set admission status to BLOCKED
AND reason_code SHALL be POLICY_DENIED
AND fresh work intake SHALL NOT be permitted until reconciliation creates an isolated managed repository root.

### Requirement: Workspace isolation admission fence

The system SHALL evaluate workspace isolation pre-conditions prior to transitioning any job from READY to IN_PROGRESS.

#### Scenario: Admission fence blocks work when workspace isolation is unproven
GIVEN a job evaluated by ReadinessService for execution
WHEN any workspace isolation precondition fails (missing binding, RUNTIME collision, remote mismatch, process write confinement unverified, or unverified worktree root)
THEN readiness evaluation SHALL return outcome FAILURE or UNKNOWN
AND reason_code SHALL be POLICY_DENIED or EVIDENCE_INSUFFICIENT
AND the job SHALL remain fence-blocked.
