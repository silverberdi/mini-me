## ADDED Requirements

### Requirement: Native Archive proceeds from verified Sync without semantic paragraph comparison
During DOC_CLOSING, after the existing workflow has observed a successful native Sync for the same Change and documentation worktree, the thinking agent SHALL invoke the installed OpenSpec CLI Archive command in non-interactive confirmation mode (`openspec archive -y <change-name>`). Archive completion SHALL be determined from the CLI result and observable active/archive artifacts. The system SHALL NOT block on a separate free-text or paragraph-equivalence comparison when native Sync has already succeeded. If native Archive exits unsuccessfully or the resulting archive cannot be observed, the system SHALL preserve the Change and report the CLI diagnostics; it SHALL NOT claim completion or create a manual archive substitute.

#### Scenario: Verified Sync is followed by native Archive and observable completion
- **GIVEN** native Sync for the active Change and documentation worktree completed successfully
- **WHEN** DOC_CLOSING invokes `openspec archive -y <change-name>` through the installed agent workflow
- **THEN** the native CLI result is captured
- **AND** the active Change is absent and exactly one corresponding archive entry is observable
- **AND** documentation PR preparation continues without a separate semantic paragraph-comparison gate.

#### Scenario: Native Archive failure preserves the Change
- **GIVEN** native Sync completed successfully
- **WHEN** the native Archive command exits nonzero or its expected archive result is absent or ambiguous
- **THEN** DOC_CLOSING remains incomplete and preserves the Change and worktree
- **AND** the operator-facing diagnostics identify the actual CLI or artifact verification failure.

#### Scenario: Sync was not verified
- **GIVEN** native Sync failed, is ambiguous, or has no observable successful result for this Change and worktree
- **WHEN** DOC_CLOSING considers Archive
- **THEN** the system does not treat a prior narrative or textual similarity as proof of Sync
- **AND** it follows the existing native Sync recovery or human-gate path before Archive.
