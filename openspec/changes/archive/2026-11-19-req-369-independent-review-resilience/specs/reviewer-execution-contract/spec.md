## ADDED Requirements

### Requirement: Verdict-first prompt formatting and diff hygiene
The system SHALL compose the reviewer prompt instructing that the structured review verdict JSON payload be emitted as the first line of output, and SHALL exclude dependency lockfiles and binary assets from the diff passed to the independent reviewer.

#### Scenario: Review prompt mandates JSON verdict first
- **WHEN** the orchestrator builds the prompt for independent proposal or code review
- **THEN** the prompt explicitly instructs the reviewer to output the single structured JSON verdict object immediately as its very first output line before any narrative remarks.

#### Scenario: Code review diff excludes non-code lockfiles
- **WHEN** the orchestrator extracts the git diff for a candidate change
- **THEN** package lockfiles (`package-lock.json`, `poetry.lock`, `pnpm-lock.yaml`, `yarn.lock`) are excluded from the review diff payload to preserve reviewer context budget.

#### Scenario: Code review diff resolves against remote merge base
- **WHEN** the orchestrator determines the base ancestor for the review diff
- **THEN** it resolves the diff against the remote tracking base commit (`merge-base`) rather than a potentially un-synchronized local branch reference.
