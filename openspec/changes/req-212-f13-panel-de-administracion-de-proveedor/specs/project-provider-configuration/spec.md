# Spec Delta

## ADDED Requirements

### Requirement: Administrative model catalog is separate from project connections

The provider catalog SHALL expose provider and harness metadata and model capabilities without containing project URLs, repositories, tokens, private keys, or credential contents. Project connection validation SHALL consume catalog diagnostics but SHALL preserve independent ticket-source and Git/PR connection boundaries.

#### Scenario: Catalog response contains no project secret
- **WHEN** an authenticated operator reads the administrative provider catalog
- **THEN** provider, harness, model, capability, and diagnostic metadata are returned while project connection and credential values are absent

#### Scenario: Unverified provider cannot be assigned
- **WHEN** a project profile selects a provider or harness whose catalog diagnostic is unavailable or blocked
- **THEN** validation rejects the profile before dispatch and reports the required diagnostic

### Requirement: Provider-model assignments are durable and concurrency-safe

Custom model creation or editing SHALL be transactional, idempotent by canonical provider/harness/model identity, and protected against stale updates. It SHALL not alter ticket-source or Git/PR connections and SHALL preserve an auditable origin for the resulting entry.

#### Scenario: Duplicate custom model submission
- **WHEN** the same canonical custom model is submitted twice
- **THEN** the second operation returns the persisted identity without creating a duplicate registry row

#### Scenario: Stale custom model update
- **WHEN** an edit uses an obsolete version of a registry entry
- **THEN** the update is rejected without overwriting the current model or project connection

