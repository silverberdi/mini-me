## ADDED Requirements

### Requirement: Reviewer findings are grounded in observable test evidence
The complementary reviewer SHALL evaluate test and database-isolation claims using the exact candidate SHA, repository configuration, executed commands, redacted results, and any matching project CI checks. Narrative disclaimers or agent assertions alone SHALL NOT establish that a test was run, passed, failed, or is impossible; the reviewer SHALL identify a concrete contradiction or missing observable evidence before treating a test claim as a blocking finding. Pending deferred checks SHALL remain pending until conclusive same-SHA CI evidence exists.

#### Scenario: Reviewer accepts observable test evidence over a generic disclaimer
- **GIVEN** the candidate SHA has an observable successful configured test result or matching CI check
- **AND** a narrative disclaimer claims without contrary evidence that the test remains unverified
- **WHEN** the complementary reviewer evaluates the candidate
- **THEN** it uses the observable result and does not block solely on the disclaimer
- **AND** it cites the command or CI check and candidate SHA supporting its conclusion.

#### Scenario: Reviewer rejects unsubstantiated test completion
- **GIVEN** an agent or proposal claims a test passed but no matching command or CI result is observable for the candidate SHA
- **WHEN** the complementary reviewer evaluates the candidate
- **THEN** it does not accept the claim as evidence
- **AND** it identifies the missing command, result, or SHA binding as the specific finding.

#### Scenario: Deferred test is not misreported as complete
- **GIVEN** a required test has an authorized PR CI path but its same-SHA check is pending or unavailable
- **WHEN** the complementary reviewer evaluates the candidate
- **THEN** it reports the test as pending for that check
- **AND** it neither marks it complete nor blocks solely because it is scheduled for that later stage.
