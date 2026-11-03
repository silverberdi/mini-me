# Spec Delta

## MODIFIED Requirements

### Requirement: Native OpenSpec semantics have no local substitute
mini me SHALL NOT generate, synthesize, mutate, parse semantically, synchronize or archive OpenSpec artifacts through application code. F12 SHALL remove orphaned local emulation and semantic workflow flows, while retaining only non-semantic inspection, structural validation and evidence needed to protect repository, authorization, secret and continuity boundaries.

#### Scenario: Orphaned emulator is retired
- **WHEN** static and dynamic evidence shows that a generator, semantic parser, local verifier, merger, sync/archive substitute or its exclusive domain model has no active native-workflow consumer
- **THEN** its implementation, callers, dependencies and exclusive tests SHALL be removed in the same Change
- **AND** the official native OpenSpec workflow SHALL remain the only authoring/execution authority.

#### Scenario: Native artifact is inspected
- **WHEN** an operator or retained safety path requests status or structural validation of an existing native Change
- **THEN** mini me SHALL expose only the official structural result and repository-safe evidence
- **AND** SHALL NOT infer, generate, mutate, merge or archive semantic content.

#### Scenario: Native workflow owns semantic lifecycle
- **WHEN** an agent invokes the installed native OpenSpec propose, apply or verify workflow for an authorized Change
- **THEN** mini me SHALL preserve that workflow as the sole authority for authoring, applying and verifying semantic artifacts
- **AND** SHALL NOT synthesize, mutate, merge or substitute semantic artifacts or workflow results in application code.

#### Scenario: Native workflow result is handed off safely
- **WHEN** mini me receives an existing result or artifact from an installed native OpenSpec workflow
- **THEN** mini me SHALL expose only the native result together with repository-safe identity, authorization and evidence context
- **AND** SHALL NOT infer semantic completion or replace native propose, apply or verify behavior with a local implementation.

#### Scenario: Proposal preparation does not generate an OpenSpec change
- **WHEN** an operator requests proposal preparation for an authorized Change
- **THEN** mini me SHALL hand off proposal execution to the installed native OpenSpec workflow and preserve its produced artifacts as authoritative
- **AND** SHALL NOT create semantic OpenSpec artifacts, a synthetic success result, or a substitute workflow run in application code.

#### Scenario: Sync or archive is requested during F1
- **WHEN** a caller requests OpenSpec synchronization or archival through the authorized native workflow
- **THEN** mini me SHALL preserve the native workflow as the authority for synchronization or archival and report its result
- **AND** SHALL NOT merge Markdown, move a Change directory, or update closure state as a local substitute.

### Requirement: Reusable native-workflow handoff substrate is preserved
mini me SHALL preserve installed official OpenSpec skills, verified repository/worktree identity and candidate/evidence identity mechanisms that have a retained consumer, and SHALL remove only their legacy semantic dispatcher or other proven-orphaned wrapper.

#### Scenario: Shared identity support has a retained consumer
- **WHEN** an evaluated legacy component contains both reusable identity/evidence support and semantic emulation
- **THEN** the reusable support SHALL remain for the native workflow consumer
- **AND** the semantic emulation SHALL be retired.

#### Scenario: Legacy execution component is evaluated for removal
- **WHEN** F1 evaluates a legacy execution, pipeline, or orchestration component
- **THEN** the Removal Ledger SHALL separate its reusable native-workflow identity/evidence dependency from its semantic workflow emulation
- **AND** SHALL preserve only the former when a retained F3 consumer is evidenced
- **AND** SHALL NOT dispatch an agent or invoke a workflow in F1.
