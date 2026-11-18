## MODIFIED Requirements

### Requirement: Four independently configured project roles
Each project SHALL configure `thinking`, `execution`, `independent_review`, and `fallback` profiles with verified agent/provider, compatible model, supported effort, applicable native workflows, and references to installed skills. Thinking and execution SHALL default to medium effort where supported; sync/archive in future profiles use the minimum compatible effort. A configured fallback profile SHALL be available to the applicable provider recovery policy without a separate fallback budget authorization, daily/monthly cap, or internal headroom prerequisite. The project SHALL NOT enforce fixed Codex/Antigravity/DeepSeek/OpenRouter role pairings.

#### Scenario: Persist compatible independent profiles
- **WHEN** an operator saves four role profiles whose providers, models, effort, stages, skills, and workflows are discoverably compatible
- **THEN** mini me persists those selections against the project and uses the configured thinking role for the Greenfield context-preparation operation

#### Scenario: Reject incompatible model or effort
- **WHEN** a selected model or effort is not present in the live/configured capability evidence for that agent
- **THEN** project validation fails and the invalid profile is not used or silently downgraded

#### Scenario: Reject same-author review
- **WHEN** the selected independent reviewer resolves to the substantive author of a candidate
- **THEN** the review role is not accepted for that candidate and no self-review is presented as independent

#### Scenario: Configured fallback requires no separate artificial budget authorization
- **WHEN** a compatible fallback profile is configured and the applicable provider recovery policy permits the operation
- **THEN** the profile is selectable without a fallback authorization flag or daily/monthly budget cap

#### Scenario: Paid fallback requires authorization
- **WHEN** a configured fallback profile is selected for an operation permitted by the provider recovery policy
- **THEN** the configured profile may be invoked without a separate internal budget flag, daily/monthly cap, or headroom check; any exceptional-cost human decision required by the rector SHALL remain a separate gate
