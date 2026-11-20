## MODIFIED Requirements

### Requirement: Native Archive proceeds from verified Sync without semantic paragraph comparison
During DOC_CLOSING, after the existing workflow has observed a successful native Sync for the same Change and documentation worktree, the thinking agent SHALL invoke the installed OpenSpec CLI Archive command in non-interactive confirmation mode with spec synchronization skipped (`openspec archive --yes --skip-specs <change-name>`). Archive completion SHALL be determined from the actual agent-process result and observable active/archive artifacts. Sync and Archive SHALL NOT require a model-authored `MINIME_WORKFLOW_RESULT` completion token when the agent process succeeds and the resulting files provide the required operational evidence. The system SHALL still reject nonzero process exits, timeouts, preflight or environment failures, ambiguous results, and absent or inconsistent artifacts. An actual native workflow `HUMAN_REQUIRED` handoff SHALL remain visible and actionable. The system SHALL NOT block on a separate free-text or paragraph-equivalence comparison when native Sync has already succeeded. If native Archive exits unsuccessfully or the resulting archive cannot be observed, the system SHALL preserve the Change and report the available diagnostics; it SHALL NOT claim completion or create a manual archive substitute.

#### Scenario: Verified Sync is followed by native Archive and observable completion
- **GIVEN** native Sync for the active Change and documentation worktree completed successfully
- **WHEN** DOC_CLOSING invokes the official Archive workflow
- **THEN** the workflow invokes `openspec archive --yes --skip-specs <change-name>`
- **AND** the native CLI result is captured
- **AND** the active Change is absent and exactly one corresponding archive entry with its required artifacts is observable
- **AND** documentation PR preparation continues without a separate semantic paragraph-comparison gate.

#### Scenario: Deterministic workflow completion does not depend on a model token
- **GIVEN** a native Sync or Archive agent process exits successfully without timeout or environment failure
- **AND** the operation's required resulting filesystem state is independently observable
- **WHEN** DOC_CLOSING evaluates the operation
- **THEN** it accepts the operation without requiring `MINIME_WORKFLOW_RESULT: {"status":"COMPLETE", ...}`
- **AND** it does not accept a narrative alone when the process failed or the required filesystem state is absent, incomplete, or ambiguous.

#### Scenario: A real native human handoff remains actionable
- **GIVEN** the Sync or Archive workflow emits a valid `HUMAN_REQUIRED` handoff for a genuine decision
- **WHEN** the coordinator receives the result
- **THEN** it preserves the current question and original options for the operator
- **AND** it does not convert the handoff into successful completion.

#### Scenario: Native Archive failure preserves the Change
- **GIVEN** native Sync completed successfully
- **WHEN** the native Archive command exits nonzero or its expected archive result is absent or ambiguous
- **THEN** DOC_CLOSING remains incomplete and preserves the Change and worktree
- **AND** the operator-facing diagnostics identify the actual process or artifact verification failure.

#### Scenario: Sync was not verified
- **GIVEN** native Sync failed, is ambiguous, or has no observable successful result for this Change and worktree
- **WHEN** DOC_CLOSING considers Archive
- **THEN** the system does not treat a prior narrative or textual similarity as proof of Sync
- **AND** it follows the existing native Sync recovery or human-gate path before Archive.

### Requirement: Archived OpenSpec changes are committed before PR2 progression
Before DOC_CLOSING advances to PR2 preparation, the system SHALL ensure that the verified archive and synchronized `openspec/` changes are present in the documentation branch's Git history. On re-entry where the Change is already archived, the system SHALL inspect Git state and commit pending `openspec/` changes before advancing. It SHALL NOT report PR2 readiness while relevant OpenSpec changes remain uncommitted or while the committed candidate cannot be verified. It SHALL NOT include unrelated staged changes in that commit.

#### Scenario: Completed archive with pending OpenSpec changes is committed before PR2
- **GIVEN** the active Change is absent and exactly one complete matching archive is present with synchronized main specs
- **AND** the documentation worktree has pending changes under `openspec/`
- **WHEN** DOC_CLOSING re-enters and observes the completed archive
- **THEN** the pending OpenSpec paths are committed to the documentation branch
- **AND** the clean OpenSpec state and documentation branch head are verified before transition to PR2 preparation.

#### Scenario: Archive and synchronized specs are already committed
- **GIVEN** the completed archive and synchronized main specs are present in the documentation branch's current commit
- **AND** no relevant OpenSpec changes remain uncommitted
- **WHEN** DOC_CLOSING observes the completed archive
- **THEN** it proceeds to PR2 preparation without rerunning Sync or Archive or creating an empty commit.

#### Scenario: OpenSpec commit cannot be safely completed
- **GIVEN** OpenSpec changes remain pending but cannot be committed safely or the resulting commit cannot be verified
- **WHEN** DOC_CLOSING considers advancing to PR2
- **THEN** it remains in DOC_CLOSING with the concrete Git failure
- **AND** it does not include unrelated staged changes or claim PR2 readiness.
