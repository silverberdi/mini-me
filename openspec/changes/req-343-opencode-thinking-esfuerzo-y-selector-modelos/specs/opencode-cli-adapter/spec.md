## MODIFIED Requirements

### Requirement: Role separation and review independence

The adapter MUST support configured `thinking`, `execution`, and `independent_review` roles while preserving read-only review constraints and denying merge, approval, ticket closure, lifecycle, and deployment authority to OpenCode.

#### Scenario: Thinking role is authorized for OpenCode
- **WHEN** an authorized `thinking` request is dispatched to OpenCode
- **THEN** OpenCode is invoked with the corresponding thinking operation (explore or propose) in the managed worktree without refusing the role

#### Scenario: Reviewer is read-only and independent
- **WHEN** OpenCode is dispatched as `independent_review`
- **THEN** it MUST receive the immutable candidate identity and permitted review inputs, MUST NOT mutate the candidate, and MUST be different from the candidate author under the project review policy

#### Scenario: OpenCode cannot self-approve or merge
- **WHEN** an OpenCode invocation produces a result for any supported role
- **THEN** the result MUST NOT authorize merge, approval, remote ticket closure, deployment, or a lifecycle transition reserved for mini me or the operator
