## ADDED Requirements

### Requirement: Global Watchdog settings in provider administration
The existing provider/model administration view SHALL expose the persisted global Watchdog provider/model, inactivity threshold, and operating mode from the Watchdog configuration API. It SHALL populate provider/model choices from the registered catalog and render only API-confirmed values and save outcomes.

#### Scenario: Load and save Watchdog settings
- **WHEN** an authorized operator opens provider administration and saves valid Watchdog settings
- **THEN** the view displays the server-confirmed provider/model, threshold, and mode
- **AND** refresh preserves the persisted values

#### Scenario: Save is rejected
- **WHEN** the API rejects an unavailable model or invalid threshold
- **THEN** the view retains the last server-confirmed settings and displays the returned error
- **AND** it does not claim the rejected settings were saved
