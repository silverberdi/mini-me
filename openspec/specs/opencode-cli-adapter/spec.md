# opencode-cli-adapter Specification

## Purpose

Define a controlled, provider-neutral OpenCode CLI adapter that lets mini me delegate approved agent work in an isolated project worktree while preserving native OpenSpec lifecycle authority, repository identity, evidence integrity, and fail-closed provider policy.

## Requirements

### Requirement: Disabled-by-default OpenCode invocation

The system MUST keep the F9 OpenCode adapter disabled until an explicit operator authorization enables it for a configured project and role. A disabled adapter MUST NOT invoke OpenCode, a model API, a scheduler, a remote ticket mutation, or a deployment.

#### Scenario: Disabled F9 refuses dispatch
- **WHEN** mini me receives an execution or independent-review request while F9 remains disabled or lacks project-role authorization
- **THEN** it MUST refuse dispatch before starting OpenCode and MUST record a non-mutating reason that the capability is not authorized

#### Scenario: Explicit authorization enables only the selected scope
- **WHEN** an operator authorizes OpenCode for one configured project and one supported role
- **THEN** the adapter MUST accept only that project-role scope and MUST leave all other projects and roles disabled

### Requirement: Isolated CLI execution in the managed worktree

An authorized OpenCode invocation MUST run in the exact managed execution or review worktree bound to the candidate and MUST NOT mutate the runtime checkout, main workspace, another project, or an unbound path.

#### Scenario: Implementer invocation is isolated
- **WHEN** an authorized `execution` request is dispatched for a candidate with a verified repository, base commit, and worktree identity
- **THEN** OpenCode MUST start in that worktree and all file/tool effects MUST be confined to its authorized boundary

#### Scenario: Binding or candidate mismatch fails closed
- **WHEN** repository, worktree, branch, candidate SHA, or ownership evidence is missing, stale, or contradictory
- **THEN** mini me MUST refuse the OpenCode invocation without filesystem mutation and MUST preserve the mismatch evidence

### Requirement: Native tool and OpenSpec boundary

The adapter MUST expose only the host CLI capabilities that OpenCode natively provides and MUST invoke the installed official OpenSpec workflows without reimplementing prompts, artifact generation, shell execution, semantic verification, sync, or archive behavior in mini me.

#### Scenario: Official workflow remains authoritative
- **WHEN** an authorized OpenCode agent performs `explore`, `propose`, `apply`, or `verify`
- **THEN** the corresponding installed OpenSpec workflow MUST remain the authority for its artifacts and lifecycle result

#### Scenario: No parallel workflow is created
- **WHEN** OpenCode is configured for a project
- **THEN** the system MUST NOT create a parallel queue, scheduler, OpenSpec generator, prompt substitute, semantic verifier, or archive/merge implementation

### Requirement: Role separation and review independence

The adapter MUST support configured `execution` and `independent_review` roles while preserving read-only review constraints and denying merge, approval, ticket closure, lifecycle, and deployment authority to OpenCode.

#### Scenario: Reviewer is read-only and independent
- **WHEN** OpenCode is dispatched as `independent_review`
- **THEN** it MUST receive the immutable candidate identity and permitted review inputs, MUST NOT mutate the candidate, and MUST be different from the candidate author under the project review policy

#### Scenario: OpenCode cannot self-approve or merge
- **WHEN** an OpenCode invocation produces a result for either supported role
- **THEN** the result MUST NOT authorize merge, approval, remote ticket closure, deployment, or a lifecycle transition reserved for mini me or the operator

### Requirement: Candidate evidence is immutable and attributable

Every authorized invocation MUST record the provider/CLI identity, role, project, worktree, input operation, observable tool result, artifacts, and outcome against the candidate SHA or an explicitly recorded immutable candidate identity.

#### Scenario: Successful tool result is attributable
- **WHEN** OpenCode reads or edits files or runs a linter/test
- **THEN** the invocation and its observable result MUST be linked to the candidate identity, including the affected artifact or command outcome

#### Scenario: Evidence cannot be attached to an unknown candidate
- **WHEN** a result lacks a verified candidate SHA or durable candidate identity
- **THEN** mini me MUST reject it as authoritative evidence and MUST NOT advance the lifecycle

### Requirement: Provider failure is fail-closed

OpenCode adapter failures, including quota exhaustion, timeout, authentication failure, unavailable host CLI, malformed output, or OpenRouter/API errors, MUST terminate the current invocation safely and delegate recovery or fallback to the existing provider policy.

#### Scenario: OpenRouter quota or timeout
- **WHEN** an OpenRouter-backed OpenCode call exhausts quota or times out
- **THEN** mini me MUST preserve the failure evidence, MUST avoid an unapproved retry or fallback spend, and MUST fail closed under the existing provider policy

#### Scenario: Partial tool failure
- **WHEN** a tool command fails or OpenCode exits with an incomplete or ambiguous result
- **THEN** the result MUST be non-authoritative until verified by the applicable official workflow and MUST NOT advance, merge, close, or deploy the candidate

### Requirement: No production responsibility

The OpenCode adapter MUST NOT deploy production systems, change production data, restart the scheduler, or close remote requests as a consequence of an invocation.

#### Scenario: Deployment-like command is requested
- **WHEN** an OpenCode task requests a production deployment, scheduler restart, or remote closure
- **THEN** the adapter MUST deny or stop the operation according to existing authorization boundaries and MUST report the denial without claiming success
