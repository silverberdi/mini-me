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

### Requirement: Authorized Patch Application
Patch application MUST execute strictly inside an authorized `EXECUTION_WORKTREE`.

#### Scenario: Worktree isolation enforcement
- **Given** a validated patch and an authorized `EXECUTION_WORKTREE`
- **When** `LocalPatchApplier` applies the patch
- **Then** `ManagedWorkspaceGuard` and `WorktreeManager` MUST authorize the target worktree, the worktree MUST be clean prior to application, and patch application MUST execute programmatically without touching runtime checkout or managed repository directly.

### Requirement: Bounded Corrective Flow and Implement-Only Authority
Local worker execution MUST remain strictly implement-only with bounded retries.

#### Scenario: Clean baseline restoration on corrective attempt
- **Given** a patch application or deterministic validation failure on attempt 1
- **When** a single corrective model attempt is permitted
- **Then** the execution worktree MUST be restored to a clean baseline before applying the corrective patch, and local worker MUST NOT possess review, audit, or merge authority.
