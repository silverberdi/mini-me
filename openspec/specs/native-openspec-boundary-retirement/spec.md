# native-openspec-boundary-retirement Specification

## Purpose

Ensures that mini me no longer substitutes native OpenSpec workflows with local semantic generation, verification, synchronization, or archival behavior.

## Requirements

### Requirement: Native OpenSpec semantics have no local substitute
mini me SHALL NOT generate the semantic contents of a proposal, design, specification, task list, sync result, or archive result through application code. It SHALL retain only non-semantic inspection and evidence needed to protect repository, authorization, secret, and continuity boundaries.

#### Scenario: Proposal preparation does not generate an OpenSpec change
- **WHEN** an operator requests preparation of work that does not already have agent-produced OpenSpec artifacts
- **THEN** mini me SHALL report that native proposal execution is not yet available in F1
- **AND** SHALL NOT create semantic OpenSpec artifacts, a synthetic success result, or a substitute workflow run.

#### Scenario: Sync or archive is requested during F1
- **WHEN** a caller requests OpenSpec synchronization or archival through mini me
- **THEN** mini me SHALL reject the operation as unavailable pending F3
- **AND** SHALL NOT merge Markdown, move a Change directory, or update closure state as a substitute.

### Requirement: Official OpenSpec integration is retained as read-only structural support
mini me SHALL retain the official OpenSpec CLI/adapter integration needed to locate, inspect and structurally validate existing native artifacts. This integration SHALL NOT author content, infer requirements, merge deltas, archive directories, or stand in for an agent workflow.

#### Scenario: Existing native Change is inspected
- **WHEN** an operator or retained safety path requests the status or structural validation of an existing native OpenSpec Change
- **THEN** mini me SHALL obtain and expose only the official structural result and repository-safe evidence
- **AND** SHALL NOT modify the Change or manufacture a semantic verdict.

### Requirement: Reusable native-workflow handoff substrate is preserved
mini me SHALL preserve the installed official OpenSpec skills, verified repository/worktree identity, and candidate/evidence identity mechanisms that have a retained F3 consumer. F1 SHALL NOT preserve a legacy semantic dispatcher merely because it contains those mechanisms.

#### Scenario: Legacy execution component is evaluated for removal
- **WHEN** F1 evaluates a legacy execution, pipeline, or orchestration component
- **THEN** the Removal Ledger SHALL separate its reusable native-workflow identity/evidence dependency from its semantic workflow emulation
- **AND** SHALL preserve only the former when a retained F3 consumer is evidenced
- **AND** SHALL NOT dispatch an agent or invoke a workflow in F1.

### Requirement: Retired lifecycle semantics do not advance work
mini me SHALL NOT execute legacy verify gates, execution prompts, orchestration transitions, recovery logic, or post-merge reconciliation when their purpose is to emulate an OpenSpec workflow. A request that reaches a retired operation SHALL fail explicitly without dispatching an agent, changing a candidate, or spending provider budget.

#### Scenario: Legacy execution request is denied
- **WHEN** a caller invokes a legacy execution or orchestration entry point after F1 migration
- **THEN** mini me SHALL return a stable unavailable result that identifies the operation as pending F3
- **AND** SHALL preserve existing Git worktrees, durable records, and historical artifacts unchanged.

#### Scenario: Read-only integrity inspection remains available
- **WHEN** an operator inspects an existing OpenSpec artifact or repository binding
- **THEN** mini me SHALL continue to provide non-semantic, read-only structural and identity information
- **AND** SHALL NOT infer, generate, mutate, merge, or archive OpenSpec content.
