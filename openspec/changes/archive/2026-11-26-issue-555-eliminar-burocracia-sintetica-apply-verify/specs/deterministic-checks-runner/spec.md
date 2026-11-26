## ADDED Requirements

### Requirement: Playwright uses the isolated runtime browser installation
The environment prepared for isolated candidate checks SHALL set `PLAYWRIGHT_BROWSERS_PATH=/opt/minime/runtime/playwright-browsers`. Playwright browser discovery SHALL use that location without depending on a user's home cache or initiating browser downloads.

#### Scenario: Playwright resolves the preinstalled runtime browser
- **GIVEN** the isolated runtime contains a Playwright browser at `/opt/minime/runtime/playwright-browsers`
- **WHEN** a candidate's Playwright check is prepared and executed
- **THEN** its environment contains `PLAYWRIGHT_BROWSERS_PATH=/opt/minime/runtime/playwright-browsers`
- **AND** Playwright resolves the installed browser from that path without using `~/.cache/ms-playwright` or `~/Library/Caches/ms-playwright`.

#### Scenario: Missing runtime browser does not trigger a download
- **GIVEN** the configured runtime browser path is absent or lacks the required browser
- **WHEN** a candidate's Playwright check is prepared
- **THEN** the check reports the runtime browser as unavailable
- **AND** it does not silently download a browser or fall back to a user cache.
