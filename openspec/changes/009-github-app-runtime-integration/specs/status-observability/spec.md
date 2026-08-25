## MODIFIED Requirements

### Requirement: Health and status surface
The system SHALL expose API and CLI status for an orchestration run and GitHub runtime identity, including project, change, run ID, current stage/checkpoint, operational job/current executor, candidate generation and SHA, base SHA, check/review/audit status and candidate bindings, provider/capacity state, retry/reassignment counters, pending handoff, GitHub App authentication mode and health, PR number/URL/head SHA when present, human gate, last deterministic transition, and structured stop detail, with secrets redacted.

#### Scenario: Operator inspects orchestration status
- **GIVEN** an orchestration run exists
- **WHEN** the operator requests `orchestrate status` through the supported API or CLI
- **THEN** the response reports the durable fields needed to identify what will happen next and why, without claiming progress from an uncommitted agent output.

#### Scenario: Status reports candidate-bound evidence
- **WHEN** a review or audit exists for a run
- **THEN** status identifies the candidate generation/SHA and base SHA to which that evidence applies, and marks prior evidence historical after remediation.

#### Scenario: Status does not expose secrets
- **WHEN** provider, subprocess, Git, or GitHub diagnostics are returned
- **THEN** credentials, tokens, private keys, and configured secret values are redacted.

#### Scenario: Operator requests Foundation status
- **GIVEN** mini me is running with registered projects
- **WHEN** the operator requests status through the supported API or CLI
- **THEN** database health, registered projects, discovered changes, GitHub App authentication mode, and readiness reasons are returned.

#### Scenario: GitHub authentication diagnostics are observable
- **WHEN** a GitHub operation fails or succeeds
- **THEN** status diagnostics indicate GitHub App authentication mode and machine-readable failure category (such as invalid credentials, unauthorized installation, remote unobservable, or repository mismatch) without revealing token or private key material.
