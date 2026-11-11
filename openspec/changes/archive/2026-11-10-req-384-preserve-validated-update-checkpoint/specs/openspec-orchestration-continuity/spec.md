## MODIFIED Requirements

### Requirement: Authorized Apply-gate decisions update the active Change before continuation
When an operator's accepted response to an Apply human gate explicitly changes the disposition of an existing Change criterion, the system SHALL preserve the original response and gate identity and SHALL coordinate the configured thinking agent to apply that decision through the native OpenSpec `update` workflow before dispatching another Apply invocation. mini me SHALL NOT author or directly edit the semantic OpenSpec artifacts. The update and its validation result SHALL be durably associated with the same Run, Change, branch, and worktree. A response that does not authorize a material criterion change SHALL continue through the existing gate-resolution behavior. The validated Update checkpoint SHALL also identify the task dispositions it changed and the candidate identity against which those changes were validated, so Apply recovery can reconcile only those dispositions without weakening unrelated regression checks. A later continuation-only Apply response SHALL reuse this validated checkpoint and SHALL NOT dispatch a no-op Update that overwrites it.

#### Scenario: Explicit deferral is applied through native OpenSpec Update
- **GIVEN** a Run is blocked at an Apply gate and the operator explicitly directs that an existing validation criterion be deferred or reclassified
- **WHEN** the accepted gate response is processed
- **THEN** the configured thinking agent receives the original decision and current Change context through the native OpenSpec `update` workflow
- **AND** no Apply invocation is dispatched until the updated artifacts pass strict OpenSpec validation
- **AND** the response, Update invocation, result, and validation evidence are linked to the same Run, Change, branch, and worktree.

#### Scenario: Ambiguous or unauthorized disposition remains at the human gate
- **GIVEN** an operator response could materially change a criterion but is ambiguous, conflicts with the rector contract, or does not authorize the needed change
- **WHEN** the system evaluates the response
- **THEN** it asks one current, concrete human question with the valid options and their effects
- **AND** it dispatches neither OpenSpec Update nor Apply until the decision is resolved
- **AND** it does not consume an Apply attempt for this unresolved decision.

#### Scenario: Interrupted or repeated response does not duplicate Update or Apply
- **GIVEN** the operator response has a durable action identity and its OpenSpec Update invocation may have started or completed
- **WHEN** the same response is replayed or the coordinator recovers after interruption
- **THEN** the system observes the existing action, invocation, and updated-artifact validation before deciding the next step
- **AND** it does not apply the same decision twice or create duplicate Apply invocations
- **AND** it resumes from the validated checkpoint while preserving prior evidence.

#### Scenario: Native Update is unavailable or validation fails
- **GIVEN** the configured thinking agent cannot resolve the native OpenSpec Update workflow or the updated Change fails strict validation
- **WHEN** the system processes an authorized disposition
- **THEN** it preserves the Run, worktree, response, and invocation evidence
- **AND** reports the concrete missing capability or validation error and the next valid operator choices
- **AND** does not fall through to a generic Apply retry.

#### Scenario: Validated Update binds reclassified tasks to the same candidate
- **GIVEN** a native OpenSpec Update completes and passes strict validation
- **WHEN** the coordinator records the Update checkpoint
- **THEN** it records the explicit task disposition changes and the Run, Change, branch, worktree, and candidate identity
- **AND** Apply recovery can use that checkpoint only for the changed task dispositions
- **AND** replaying the same operator action does not broaden the set of reconciled tasks.

#### Scenario: Continuation-only Apply response preserves the validated checkpoint
- **GIVEN** a validated Update checkpoint from an earlier accepted operator action remains bound to the current Run, Change, branch, worktree, and candidate
- **AND** the current Apply gate response authorizes continuation without changing criteria
- **WHEN** the coordinator processes the response
- **THEN** it reuses the existing validated checkpoint and retains its original operator-action identity
- **AND** it dispatches no no-op Update and does not replace the checkpoint with an empty disposition set.
