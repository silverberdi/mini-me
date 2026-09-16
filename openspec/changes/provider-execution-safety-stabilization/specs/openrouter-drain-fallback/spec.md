## ADDED Requirements

### Requirement: No fabricated implementation candidates
The system SHALL NOT fabricate an implementation candidate when a provider returns a textual success but no real repository-editing harness has materially applied repository changes for the requested task. When OpenRouter is selected as an implementer but no real repository-editing harness exists, the system SHALL return a truthful governed failure/escalation outcome, SHALL NOT modify the repository, SHALL NOT create a placeholder candidate file, SHALL NOT create a candidate commit, SHALL NOT claim implementation success, and SHALL NOT persist a false progress lifecycle event.

#### Scenario: OpenRouter success without repository materialization creates no candidate
- **WHEN** OpenRouter implementer fallback returns a successful text response but no real repository-editing harness exists
- **THEN** the system SHALL NOT create a candidate artifact (including any `candidate_impl.py`), SHALL NOT create a candidate commit, and SHALL return a truthful governed failure/escalation outcome.

#### Scenario: No false progress event for a non-materialized candidate
- **WHEN** an implementer path concludes without material repository changes
- **THEN** the system SHALL NOT persist a lifecycle progress event or candidate record implying implementation success.

#### Scenario: OpenRouter outcome never claims implementation success without a candidate
- **WHEN** an OpenRouter call returns success but no candidate-bound material change exists to review
- **THEN** the system SHALL classify the attempt truthfully (for example `EVIDENCE_INSUFFICIENT` or `PROVIDER_FAILURE`) and SHALL NOT advance the job as if implementation completed.
