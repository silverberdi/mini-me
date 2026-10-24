## Purpose
Allow a prepared project to add documentary context by an auditable new PR while retaining all previously approved context until an authorized merge. Real project merges require human authorization; exclusively disposable F2 acceptance-test PRs may be merged by their controlled test harness after exact identity/integrity verification.

## ADDED Requirements

### Requirement: Incremental context update preserves approved context and provenance
An incremental ZIP SHALL be accepted only for an existing prepared project and SHALL be processed by its configured thinking agent against the currently approved main context. The update SHALL preserve source provenance and prior decisions, distinguish additions from explicitly requested replacements, identify duplicates and unresolved contradictions, and SHALL NOT behave as reset/reinitialization or invent product content. A contradiction without an explicit replacement SHALL preserve the approved decision as authoritative, retain and classify the new source, record both source references and the contradiction, and include it in the review PR. A documentary contradiction alone SHALL NOT block PR creation; only a real safety, permission, integrity/fidelity, or publication failure may block it.

#### Scenario: Add a complementary context package
- **WHEN** an operator submits a valid new ZIP for a prepared project
- **THEN** the agent compares it against approved context, incorporates supported complementary content with new provenance, and preserves prior sources/decisions

#### Scenario: Existing information is contradicted without explicit replacement
- **WHEN** new source material conflicts with an approved decision and no explicit replacement is supplied
- **THEN** the earlier approved decision remains authoritative, the new document is retained and classified, both sources and the contradiction are recorded in the candidate PR, and the contradiction alone does not prevent creating that PR

#### Scenario: Explicit replacement is supplied
- **WHEN** the operator clearly marks a source/decision as replaced
- **THEN** the candidate records both prior and replacement provenance and makes the replacement effective only after its PR merges


### Requirement: Use the same canonical F2 catalog for incremental context

An incremental ZIP SHALL be organized into the same fixed standard context file paths used by initial Greenfield bootstrap. The thinking agent SHALL read the new source files and update the applicable already-approved canonical documents on a **new PR branch**, allowing the same sourced information to appear in multiple relevant documents. Previously approved material and original sources SHALL not be silently removed or replaced, and no new backlog, tickets, roadmap strategy, product requirements or OpenSpec tasks SHALL be invented.

Original new ZIP files SHALL remain intact under their own revision-bound `context/incoming/<sha>/`. The generated index SHALL list only substantively populated canonical documents and provide navigation to all source revisions; absent/empty documents SHALL be omitted. No business or semantic review gate is introduced in F2. Repository, ZIP, source-provenance and secret safety checks remain applicable. Approved context changes only upon observed merge of the exact PR.

#### Scenario: A new ZIP enriches several existing documents
- **WHEN** the new information concerns several canonical catalog subjects
- **THEN** the agent adds source-backed content to every relevant document and updates the navigation index without creating new categories

#### Scenario: The new ZIP contains a backlog
- **WHEN** the incoming material includes a historical backlog or roadmap
- **THEN** the documents remain contextual source/planning information, not a work queue or OpenSpec task list

#### Scenario: An optional file is empty
- **WHEN** an optional canonical document has no information after an incremental import
- **THEN** the file is omitted from the navigation index and the agent does not invent filler

### Requirement: Publish incremental context through a new branch and PR
Every valid incremental update SHALL branch from the latest verified main, produce a separate commit/PR, and leave the approved main and effective project context unchanged until that exact PR is observed merged. Unmerged context SHALL NOT be mixed into any future worktree or candidate.

#### Scenario: Incremental PR is open
- **WHEN** a context update commit and PR are published but remain unmerged
- **THEN** the project's effective context continues to reference the last merged main SHA and the new context remains pending

#### Scenario: Incremental PR is merged
- **WHEN** the exact update PR/head is observed merged into the expected repository and main branch
- **THEN** the effective context pointer advances to the merged SHA and the update is recorded as approved

#### Scenario: Repeated request after uncertain response
- **WHEN** the same package/revision is retried after an unknown PR response
- **THEN** mini me reconciles the existing branch/commit/PR by durable identity and does not repeat paid agent work or create duplicate PRs

### Requirement: Reject unusable or unsafe incremental packages without fake publication
Invalid, empty, unsafe, over-budget, or capability-incompatible packages SHALL not create a context commit/PR or update the effective context. Security and archive rules SHALL match initial ingestion.

#### Scenario: Incremental package has no usable supported content
- **WHEN** a validly encoded ZIP contains no usable documentary content or fails fidelity/provenance validation
- **THEN** mini me reports the failure, retains the previous effective context, and creates no fake PR
