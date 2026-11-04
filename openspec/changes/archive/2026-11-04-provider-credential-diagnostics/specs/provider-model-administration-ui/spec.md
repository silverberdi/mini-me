## MODIFIED Requirements

### Requirement: Defer credential testing to its owning issue
The administration view SHALL provide a “Test Connection” control for each catalog model provider and SHALL invoke the authenticated provider diagnostic endpoint only when the operator activates that control. It SHALL display the returned status, measured latency when available, and sanitized detail from the server. It SHALL NOT simulate a successful result or claim success when the request or diagnostic fails.

#### Scenario: Render connection test handoff
- **WHEN** the operator views a provider in the administration panel
- **THEN** the “Test Connection” control is visible and does not invoke a diagnostic until activated

#### Scenario: Test a catalog provider connection
- **WHEN** the operator activates “Test Connection” for a catalog model provider
- **THEN** the view calls `POST /api/v1/admin/providers/{provider}/test` for that provider and displays the server-returned status, latency, and detail

#### Scenario: Show unavailable diagnostic
- **WHEN** the server reports that no bounded non-inference check is available for the provider
- **THEN** the view shows the unavailable status and does not claim that credentials or connectivity were verified

#### Scenario: Show failed diagnostic
- **WHEN** the request fails or the server reports an unsuccessful diagnostic
- **THEN** the view shows the failure detail without displaying success or changing provider/model configuration
