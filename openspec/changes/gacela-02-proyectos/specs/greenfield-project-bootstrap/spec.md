## Purpose
Prepare a new Greenfield repository from supplied context through official OpenSpec setup to a real first PR, without writing to its main branch or starting ticket execution.

## ADDED Requirements

### Requirement: Validate repository, access, branch, workspace, and selected capabilities before mutation
Before creating a bootstrap branch or invoking an agent, mini me SHALL verify the authenticated operator, repository URL/identity, selected base branch (defaulting to `main` when omitted), configured GitHub connection and required permissions, project/workspace binding, ZIP validity, budget authorization, selected thinking-agent file-edit capability, Node/OpenSpec prerequisites, and the complete official OpenSpec integration available and compatible with the verified CLI version for every selected agent. Validation failure SHALL preserve main and avoid protected side effects.

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
- **WHEN** repository access, write/PR permission, CLI dependency, selected-agent workflow, workspace guard, or authorized budget is absent
- **THEN** onboarding blocks before bootstrap mutation or paid agent dispatch and reports the exact missing capability

### Requirement: Install and configure official OpenSpec integrations in the isolated workspace
The bootstrap SHALL verify the actual official OpenSpec CLI version and its available capabilities, install/check dependencies, and use only the setup/configuration operations supported by that version. For every selected agent it SHALL install/configure the complete set of official commands, skills, and workflows available and compatible with that version, including extended operations such as Verify, Sync, and Archive when offered—not merely the subset immediately used by the selected profiles. It SHALL verify real installed capabilities rather than assume historical names or options. It SHALL NOT create wrappers that emulate OpenSpec or overwrite compatible existing instructions.

#### Scenario: Complete official installation is available
- **WHEN** the isolated workspace has the verified official CLI version and dependencies plus the complete available compatible official integration set for every selected agent
- **THEN** OpenSpec's own status/instructions/validation confirm the installation before context changes are committed

#### Scenario: Official integration is incomplete
- **WHEN** the version-compatible official command/skill/workflow set for a selected agent is missing an available operation or required dependency
- **THEN** setup installs/configures it through supported official mechanisms or blocks; it does not report the integration complete or emulate the missing operation

### Requirement: Publish the first bootstrap change only on a protected branch and PR
All bootstrap file/Git writes SHALL occur on an independent branch rooted at the verified base; the default/main branch SHALL remain unchanged. After validation, mini me SHALL commit, push, and create one queryable first PR with exact base/head identities. For an actual onboarded project, human review/approval/merge SHALL be the first human intervention expected in a valid onboarding flow; mini me SHALL NOT merge that project's PR. An isolated, disposable F2 acceptance-test harness MAY merge a PR belonging exclusively to its test repository after verifying the exact repository, branch, head SHA, expected base, context integrity and test scope; this exemption SHALL NOT enable a general-purpose automatic merge in mini me or apply to any real project.

#### Scenario: Bootstrap successfully reaches a real PR
- **WHEN** official configuration and faithful context pass integrity validation
- **THEN** the candidate is committed and pushed on the bootstrap branch and one PR is created against the configured main branch with observable SHAs

#### Scenario: Main branch is protected from writes
- **WHEN** any bootstrap operation is attempted
- **THEN** it targets only the bound bootstrap branch, and a write targeting main is denied before Git mutation

#### Scenario: PR creation outcome is ambiguous
- **WHEN** GitHub response is lost after a PR request
- **THEN** mini me queries GitHub by bound base/head before retrying and reuses the matching PR or blocks without creating a duplicate

### Requirement: Project becomes prepared only after confirmed merge
An open, rejected, closed, stale, or unobservable bootstrap PR SHALL NOT make a project prepared. Only provider-observed merge of the exact bound bootstrap PR/head into the expected main/base SHALL transition onboarding to `PREPARED`; F2 SHALL NOT begin remote ticket processing after that transition.

#### Scenario: Bootstrap PR remains open
- **WHEN** the first PR is created but not merged
- **THEN** onboarding remains `PR_PENDING` and reports approval/merge as outstanding

#### Scenario: Exact PR merge is confirmed
- **WHEN** the Git/PR adapter observes that the bound PR/head merged into the configured main branch
- **THEN** onboarding records merge identity and becomes `PREPARED`/activatable without invoking ticket processing or a scheduler

#### Scenario: PR or base changed before merge observation
- **WHEN** the observed PR, head SHA, repository, or base differs from the durable candidate identity
- **THEN** onboarding becomes blocked and does not mark the project prepared
