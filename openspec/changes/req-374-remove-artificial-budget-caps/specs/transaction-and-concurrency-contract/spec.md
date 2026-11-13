## REMOVED Requirements

### Requirement: Budget and Provider Probe Lock Preservation
**Reason**: Locking the OpenRouter policy row solely to serialize daily/monthly cap reservations is obsolete when those caps no longer authorize provider dispatch.
**Migration**: Remove the policy-row lock and cap reservation path. Preserve provider-probe locks and transactional/idempotent writes for retained usage evidence and reviewer controls.

## ADDED Requirements

### Requirement: Usage evidence remains transactionally consistent
Writes that record provider usage, reconcile an unresolved provider outcome, or settle retained reviewer reservations SHALL remain transactional and idempotent; they SHALL NOT require a daily/monthly OpenRouter policy row or cap lock.

#### Scenario: Concurrent provider outcomes retain distinct evidence
- **WHEN** two provider calls for a project complete concurrently with observable usage results
- **THEN** each result is persisted once with its provider and request identity without a project cap-row lock

#### Scenario: Retried persistence does not duplicate usage evidence
- **WHEN** a usage persistence command is retried with the same provider request identity
- **THEN** the existing evidence is reused or deduplicated according to its idempotency key and no duplicate charge record is created

#### Scenario: Reviewer reservation controls remain intact
- **WHEN** a reviewer path uses a separately configured reviewer-specific spend control
- **THEN** its existing transactional reservation and concurrency guarantees remain enforced independently of OpenRouter daily/monthly policy
