# Spec: Local Worker Code Edit Execution

## ADDED Requirements

### Requirement: Structured Patch Contract
`LocalWorkerResult` MUST support structured patch payloads containing unified diff strings.

#### Scenario: Unified diff patch payload
- **Given** a local worker execution result from Ollama
- **When** the model proposes code modifications
- **Then** `LocalWorkerResult.patch` MUST contain a valid unified diff string and `files_changed` advisory list.

### Requirement: Deterministic Patch Policy Validation
Before any filesystem mutation, mini me MUST validate the proposed patch against strict security policy.

#### Scenario: Touched files authorization check
- **Given** a proposed unified diff patch
- **When** mini me parses the authoritative touched files from the diff
- **Then** all touched files MUST be a subset of `LocalTaskEnvelope.allowed_files` and MUST NOT contain path traversal, absolute paths, or targets outside the authorized execution worktree.

#### Scenario: Fail-closed patch safety restrictions
- **Given** a proposed patch or direct `LocalPatchApplier` invocation
- **When** mini me evaluates patch content, target paths, or envelope constraints
- **Then** patch policy validation and `LocalPatchApplier` MUST fail closed without filesystem mutation if `allowed_files` is empty, if touched files match forbidden globs or forbidden surface families, if patch contains file creation, deletion, rename, or binary diffs, or if touched paths contain symlinks or path traversal escapes.

### Requirement: Authorized Patch Application
Patch application MUST execute strictly inside an authorized `EXECUTION_WORKTREE`.

#### Scenario: Worktree isolation enforcement
- **Given** a validated patch and an authorized `EXECUTION_WORKTREE`
- **When** `LocalPatchApplier` applies the patch
- **Then** `ManagedWorkspaceGuard` and `WorktreeManager` MUST authorize the target worktree, the worktree MUST be clean prior to application, and patch application MUST execute programmatically without touching runtime checkout or managed repository directly.

### Requirement: Bounded Corrective Flow and Implement-Only Authority
Local worker execution MUST remain strictly implement-only with bounded retries.

#### Scenario: Corrective attempt restriction prior to filesystem mutation
- **Given** a malformed output or pre-mutation patch policy failure on attempt 1
- **When** a single corrective model attempt is permitted prior to filesystem mutation
- **Then** a single corrective attempt MAY occur before any filesystem mutation; once a patch is applied to disk, no local rollback or second corrective attempt is permitted, and local worker MUST NOT possess review, audit, or merge authority.
