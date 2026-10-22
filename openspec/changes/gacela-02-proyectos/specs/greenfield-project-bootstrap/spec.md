## Purpose
Prepare a new Greenfield repository from supplied context through official OpenSpec setup to a real first PR, without writing to its main branch or starting ticket execution.

## ADDED Requirements

### Requirement: Validate repository, access, branch, workspace, and selected capabilities before mutation
Before creating a bootstrap branch or invoking an agent, mini me SHALL verify the authenticated operator, repository URL/identity, selected base branch, configured GitHub connection and required permissions, project/workspace binding, ZIP validity, budget authorization, selected thinking-agent file-edit capability, Node/OpenSpec prerequisites, and required native workflows. Validation failure SHALL preserve main and avoid protected side effects.

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
The bootstrap SHALL use the official OpenSpec CLI and its supported initialization/configuration/profile operations, verify its version/dependencies, and ensure the selected agents' required native workflows/skills—including Verify when required—are actually available in the repository/runtime. It SHALL NOT install only an insufficient basic profile, create workflow wrappers that emulate OpenSpec, or overwrite compatible existing instructions.

#### Scenario: Complete official installation is available
- **WHEN** the isolated workspace has the official CLI, prerequisites, project configuration, and all selected-agent workflows required by configured profiles
- **THEN** OpenSpec's own status/instructions/validation confirm the installation before context changes are committed

#### Scenario: Basic profile omits required operation
- **WHEN** official setup exposes only a basic subset and a selected role requires a missing native operation such as Verify
- **THEN** setup installs/configures the official supported integration or blocks; it does not report the profile ready

### Requirement: Publish the first bootstrap change only on a protected branch and PR
All bootstrap file/Git writes SHALL occur on an independent branch rooted at the verified base; the default/main branch SHALL remain unchanged. After validation, mini me SHALL commit, push, and create one queryable first PR with exact base/head identities. Human review/approval/merge SHALL be the first human intervention expected in a valid onboarding flow; mini me SHALL NOT merge it.

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
