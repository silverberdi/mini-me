# Spec Delta

## MODIFIED Requirements

### Requirement: Multi-Breakpoint Responsive Layout
The system SHALL offer the same five independent Spanish views on desktop, tablet and mobile with light/dark themes, keyboard and screen-reader access, visible focus, adequate contrast, touch targets and zoom/reflow. Desktop SHALL be a readable control center with proportionate scrolling regions; tablet SHALL support master/detail; mobile SHALL navigate focused views/details without horizontal content loss. Only two primary destinations SHALL remain across devices; missing backend authority SHALL remain disabled everywhere.

#### Scenario: View PWA on ultrawide desktop
- **WHEN** the PWA loads in a 2560px-wide viewport
- **THEN** the selected view uses the available width for readable content and contextual detail without horizontal overflow or excessive blank regions, preserving two primary destinations rather than restoring the retired Queue/Pipeline/Inspector composition.

#### Scenario: View PWA on mobile device
- **WHEN** the PWA loads in a 390px-wide viewport
- **THEN** it presents a focused single-column view with touch-friendly navigation, access to all five routes through two primary destinations and contextual links, and navigated detail without horizontal content loss.

#### Scenario: Desktop control center
- **WHEN** the operator uses 1440×900 or 1920×1080
- **THEN** only the selected view occupies the main area, readable gauges and contextual detail use available space without five stacked screens or large reserved empty panels.

#### Scenario: Tablet and mobile parity
- **WHEN** the operator uses tablet 1024×768 or 768×1024, or mobile 390×844 or 360×800
- **THEN** all five routes remain reachable, Proyectos uses master/detail on tablet and navigated detail on mobile, and authorized human attention is usable by touch.

#### Scenario: Accessible themes and reflow
- **WHEN** the operator switches theme, navigates by keyboard or screen reader, or zooms to 200–400 percent
- **THEN** controls, disabled reasons, error states and stage content remain readable with logical focus, text alternatives to charts and no essential content loss.

### Requirement: Service Worker Static Shell Caching and Offline Resilience
The system SHALL cache only public static shell resources and SHALL NOT cache authenticated operational responses, decisions, credentials or Request bodies in service-worker storage or persistent browser stores. Network failure SHALL preserve a usable shell with explicit offline/stale status and observed timestamps; mutations SHALL be unavailable offline and SHALL NOT be queued for later replay. Reconnection SHALL refresh reads before permitting authority-dependent actions.

#### Scenario: Backend disconnection handling
- **WHEN** the loaded PWA cannot reach the backend during the next polling cycle
- **THEN** the shell remains usable with an explicit Spanish disconnected status, any retained in-memory observations are labeled stale with their observation time, and mutations are blocked without queuing decisions or persisting operational data.

#### Scenario: Automatic reconnection recovery
- **WHEN** backend connectivity returns while the disconnected status is displayed
- **THEN** the single refresh lifecycle refreshes authoritative reads automatically, clears the disconnection indicator after successful recovery and permits actions only after current authority is verified, without replaying mutations.

#### Scenario: Disconnect and reconnect
- **WHEN** a loaded PWA loses and later regains API connectivity
- **THEN** it shows an offline state, labels any retained in-memory observations stale, blocks mutations and refreshes authority on reconnection without replaying decisions.

#### Scenario: Logout and service-worker update
- **WHEN** the operator logs out or the static shell version changes
- **THEN** authenticated in-memory content is cleared on logout, obsolete shell caches are retired on update, and cache inspection contains no operational API response or authenticated document.
