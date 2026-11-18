## MODIFIED Requirements

### Requirement: Validate repository, access, branch, workspace, and selected capabilities before mutation
Before creating a bootstrap branch or invoking an agent, mini me SHALL verify the authenticated operator, repository URL/identity, selected base branch (defaulting to `main` when omitted), configured GitHub connection and required permissions, project/workspace binding, ZIP validity, selected thinking-agent file-edit capability, Node/OpenSpec prerequisites, and the complete official OpenSpec integration available and compatible with the verified CLI version for every selected agent. Validation failure SHALL preserve main and avoid protected side effects.

#### Scenario: Existing main branch is used
- **WHEN** the requested main branch exists and repository identity/permissions are verified
- **THEN** the bootstrap base SHA is recorded from that branch and an independent bootstrap branch is created from it

#### Scenario: Requested branch does not exist
- **WHEN** the named main branch is absent but the remote default/base can be proven and the configured GitHub identity can create a branch
- **THEN** mini me creates the requested branch using available Git/GitHub capability and records its resulting identity; otherwise it blocks with verifiable reason

#### Scenario: Empty repository has no provable base commit
- **WHEN** neither the requested nor a remote default branch has a commit from which to create the requested main branch
- **THEN** onboarding blocks with the observable empty-repository reason and does not invent a README, commit, or product context

#### Scenario: Required permission or prerequisite is missing
- **WHEN** repository access, write/PR permission, CLI dependency, selected-agent workflow, or workspace guard is absent
- **THEN** onboarding blocks before bootstrap mutation or paid agent dispatch and reports the exact missing capability
