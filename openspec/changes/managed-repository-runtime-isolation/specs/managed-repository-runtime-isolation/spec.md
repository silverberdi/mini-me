# Spec: Managed Repository Runtime Isolation

## ADDED Requirements

### Requirement: Strict physical and logical separation of runtime checkout and managed repositories

The system SHALL enforce physical and logical path isolation between mini me's deployed runtime checkout (`RUNTIME`), managed project repository roots (`MANAGED_REPOSITORY`), ephemeral execution worktrees (`EXECUTION_WORKTREE`), and project OpenSpec workspaces (`PROJECT_OPENSPEC_WORKSPACE`).

#### Scenario: Runtime checkout and managed repository root path collision denied
GIVEN a project registration or onboarding request specifying a managed repository path
WHEN the target path equals, contains, or is contained by the deployed RUNTIME checkout
THEN the system SHALL reject the path binding with outcome FAILURE
AND reason_code SHALL be POLICY_DENIED
AND SHALL NOT permit managed repository operations in the RUNTIME checkout.

#### Scenario: Mutating SDLC action against RUNTIME denied
GIVEN an active project job attempting a file write, git commit, branch operation, or OpenSpec mutation
WHEN the target path resolves inside the deployed RUNTIME checkout
THEN ManagedWorkspaceGuard SHALL deny the operation with outcome FAILURE
AND reason_code SHALL be POLICY_DENIED
AND the live RUNTIME process files SHALL remain untouched.

### Requirement: Self-hosting isolation for mini me managing itself

When mini me executes SDLC tasks for its own repository (`mini-me`), the system SHALL maintain strict filesystem and repository distinction between the deployed runtime checkout and the managed project repository.

#### Scenario: Self-hosting mini me executes task in isolated managed worktree
GIVEN mini me executing a change for project identity "mini-me"
WHEN an implementer or reviewer agent receives work instructions
THEN the execution path SHALL resolve strictly under `<managed-root>/mini-me/worktrees/<run-id>`
AND file modifications SHALL NOT touch the live deployed RUNTIME checkout (e.g. `/opt/minime/app`)
AND equality of commit SHA or repository URL between RUNTIME and managed project SHALL NOT authorize RUNTIME workspace access.

### Requirement: Verified project managed-repository binding

Every managed project SHALL maintain an authoritative, persisted `ProjectManagedRepositoryBinding` containing project identity, canonical Git remote URL, managed repository root path, worktree parent directory, and ownership marker filename, and path guessing or `cwd` heuristics SHALL be strictly forbidden.

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

All filesystem edits, Git operations, worktree creation/deletion, and OpenSpec operations across mini me SHALL pass through a central `ManagedWorkspaceGuard` before execution.

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

### Requirement: Fail-closed Git identity and remote verification

Before permitting mutations in a managed repository or worktree, the system SHALL verify Git repository root, expected Git remote URL, and ownership marker integrity.

#### Scenario: Git remote identity mismatch blocks execution
GIVEN a managed repository path being verified by ManagedWorkspaceGuard
WHEN `git remote get-url origin` returns a remote URL differing from `binding.canonical_git_remote`
THEN verification SHALL return outcome FAILURE
AND reason_code SHALL be CONFLICT
AND all mutating operations on that repository SHALL be BLOCKED.

#### Scenario: Corrupted Git repository or unobservable remote returns UNKNOWN
GIVEN a managed repository path
WHEN `git rev-parse --show-toplevel` or remote query encounters I/O failure or corrupted `.git` directory
THEN verification SHALL return outcome UNKNOWN
AND reason_code SHALL be UNOBSERVABLE
AND mutation SHALL be strictly BLOCKED.

### Requirement: Worktree ownership and safe cleanup protocol

Execution worktrees SHALL be created with explicit, verifiable ownership metadata (`.minime-worktree.json`), and cleanup operations SHALL NEVER delete unowned, un-marked, or ambiguous directories.

#### Scenario: Ephemeral worktree created with verified ownership metadata
GIVEN a request to spawn an execution worktree for job J and run R
WHEN WorktreeManager creates the worktree under `<managed-root>/<project-id>/worktrees/<run-id>`
THEN it SHALL write a `.minime-worktree.json` metadata file recording project_id, job_id, run_id, change_name, source_repository, base_sha, and branch
AND failure to write or verify the metadata file SHALL abort worktree initialization with outcome FAILURE and reason_code POSTCONDITION_NOT_PROVEN.

#### Scenario: Worktree cleanup skips unowned or ambiguous directory
GIVEN a cleanup task inspecting directory `<managed-root>/<project-id>/worktrees/unowned-folder`
WHEN `.minime-worktree.json` metadata is missing, unparseable, or contains a mismatched project_id
THEN cleanup SHALL skip deletion of the directory
AND SHALL return outcome UNKNOWN with reason_code EVIDENCE_INSUFFICIENT
AND SHALL flag the directory for human review.

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

### Requirement: Explicit deployment boundary and runtime immutability

The boundary between candidate development and runtime deployment SHALL be explicit and unidirectional, and deployment operations SHALL NOT grant managed workspace semantics to the RUNTIME checkout.

#### Scenario: Deployment updates RUNTIME from verified candidate without granting managed workspace role
GIVEN a deployment process promoting a verified candidate commit SHA to RUNTIME
WHEN deployment completes successfully and service restarts
THEN RUNTIME SHA SHALL equal the candidate SHA
BUT RUNTIME workspace role SHALL remain strictly `RUNTIME` (read-only for SDLC)
AND direct agent edits, branch creation, or OpenSpec operations on RUNTIME SHALL remain strictly DENIED (`POLICY_DENIED`).

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
WHEN any workspace isolation precondition fails (missing binding, RUNTIME collision, remote mismatch, or unverified worktree root)
THEN readiness evaluation SHALL return outcome FAILURE or UNKNOWN
AND reason_code SHALL be POLICY_DENIED or EVIDENCE_INSUFFICIENT
AND the job SHALL remain fence-blocked.
