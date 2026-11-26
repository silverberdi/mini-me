## ADDED Requirements

### Requirement: Repository Git exclusions for generated caches
Before candidate changes are evaluated or committed, the system SHALL add standard generated build-cache and temporary-artifact patterns to the repository's effective `.git/info/exclude`. For linked worktrees, Git resolves this to shared repository metadata, so the exclusions apply to all worktrees of that clone. Git-based cleanliness and Commit Guardian checks SHALL honor the effective Git exclusion rules and SHALL NOT abort solely because matching generated files exist.

#### Scenario: Generated cache files do not block candidate commit
- **GIVEN** a managed worktree contains generated files under `.angular/cache/`, `.turbo/`, `.next/cache/`, or `node_modules/.cache/`
- **WHEN** the workspace guardian prepares the worktree and Commit Guardian evaluates untracked files
- **THEN** the patterns are present in the effective exclude file returned by Git for that worktree
- **AND** Git reports those files as ignored and Commit Guardian does not abort solely because they exist.

#### Scenario: Ordinary untracked files remain visible
- **GIVEN** a managed worktree contains an untracked file that does not match an approved local exclusion
- **WHEN** Commit Guardian evaluates the worktree
- **THEN** Git continues to report that file as untracked
- **AND** the existing commit safety policy applies to it.
