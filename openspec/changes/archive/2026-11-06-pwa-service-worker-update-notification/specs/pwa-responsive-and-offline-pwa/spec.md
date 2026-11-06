## MODIFIED Requirements

### Requirement: Service Worker Static Shell Caching and Offline Resilience
The system SHALL cache only public static shell resources and SHALL NOT cache authenticated operational responses, decisions, credentials or Request bodies in service-worker storage or persistent browser stores. Network failure SHALL preserve a usable shell with explicit offline/stale status and observed timestamps; mutations SHALL be unavailable offline and SHALL NOT be queued for later replay. Reconnection SHALL refresh reads before permitting authority-dependent actions. A future Angular frontend and its service worker SHALL preserve these cache boundaries and SHALL not expose secrets or authenticated responses through offline behavior. When a new static shell version is ready, the PWA SHALL present a clear Spanish update notice with an operator action to load it; it SHALL NOT silently reload an active session.

#### Scenario: Backend disconnection handling
- **WHEN** the loaded application cannot reach the backend during the next polling cycle
- **THEN** the shell remains usable with an explicit Spanish disconnected status, any retained in-memory observations are labeled stale with their observation time, and mutations are blocked without queuing decisions or persisting operational data.

#### Scenario: Automatic reconnection recovery
- **WHEN** backend connectivity returns while the disconnected status is displayed
- **THEN** the single refresh lifecycle refreshes authoritative reads automatically, clears the disconnection indicator after successful recovery and permits actions only after current authority is verified, without replaying mutations.

#### Scenario: Disconnect and reconnect
- **WHEN** a loaded application loses and later regains API connectivity
- **THEN** it shows an offline state, labels any retained in-memory observations stale, blocks mutations and refreshes authority on reconnection without replaying decisions.

#### Scenario: Logout and service-worker update
- **WHEN** the operator logs out or the static shell version changes
- **THEN** authenticated in-memory content is cleared on logout, obsolete shell caches are retired on update, and cache inspection contains no operational API response or authenticated document.

#### Scenario: New shell version is ready
- **WHEN** the service worker confirms that a newer static shell version is ready
- **THEN** the PWA displays an accessible Spanish notice that a new version is available and an action to load it
- **AND** the active session remains on its current version until the operator chooses that action
- **AND** loading the update activates the ready shell and reloads the application.

#### Scenario: No usable service-worker update
- **WHEN** service-worker updates are unavailable or no newer shell version is ready
- **THEN** the PWA does not display a false update notice and the existing shell remains usable.
