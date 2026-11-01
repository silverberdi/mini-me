# Spec Delta

## Purpose

Mejora la PWA con una representación compacta y accesible de capacidad y una única proyección reactiva del estado operativo, manteniendo coherencia entre Dashboard, Trabajo, Trabajo actual, Backlog y refresco manual.

## ADDED Requirements

### Requirement: Compact capacity cards
The PWA SHALL display each verified provider/model capacity as a compact card with a horizontal progress bar or balance treatment, active model, real value, status (`Normal`, `En ventana`, or `Crítico`), reset time when known, and an explicit unknown state when not verified.

#### Scenario: Responsive verified quota card
- **WHEN** a verified five-hour observation is available on desktop or mobile
- **THEN** the card presents its provider/model, real remaining value, status, and reset countdown without using a semicircular gauge

#### Scenario: Unknown quota is truthful
- **WHEN** no verified capacity observation is available
- **THEN** the card displays an unavailable/unknown state and no fabricated percentage, balance, or reset countdown

### Requirement: Single reactive run projection
The PWA SHALL derive `activeRun`, `nextEligible`, and related view state from one current server snapshot so an active Run cannot also be shown as next work.

#### Scenario: Active work excluded from next work
- **WHEN** a Run is active or transitioning stages
- **THEN** Dashboard, Trabajo, Trabajo actual, and Backlog identify the same Run consistently and exclude its Request from Siguiente Trabajo

#### Scenario: Snapshot updates all views
- **WHEN** a refreshed server snapshot changes a Run stage or eligibility
- **THEN** all affected views reactively update without duplicate local copies or contradictory status labels

### Requirement: Explicit complete refresh
The navigation refresh action SHALL revalidate all observable data from the server, expose a transient synchronization indicator, and report failure without presenting stale data as current.

#### Scenario: Manual refresh succeeds
- **WHEN** the operator activates Refrescar
- **THEN** all observable collections are revalidated, the synchronization indicator is shown transiently, and the displayed timestamp reflects the completed refresh

#### Scenario: Manual refresh fails
- **WHEN** the server cannot be reached during refresh
- **THEN** the PWA marks the observation stale/offline, preserves the last timestamp, and does not claim synchronization success

### Requirement: Accessible light theme
The affected navigation, text, cards, focus indicators, and status badges SHALL meet WCAG AA contrast and remain operable in both light and dark themes.

#### Scenario: Light theme remains legible
- **WHEN** the operator selects light mode
- **THEN** sidebar, text, cards, controls, and focus states remain readable and distinguishable at the supported responsive breakpoints


### Requirement: Real-time reactive updates via EventSource
The PWA `RefreshService` SHALL subscribe to the backend Server-Sent Events stream `/api/v1/events` to ingest instantaneous state updates for runs, gates, and capacity changes while maintaining lazy polling fallback.

#### Scenario: Run transition updates UI without polling delay
- **WHEN** an SSE event arrives indicating a run stage transition or `HUMAN_REQUIRED`
- **THEN** `RefreshService` updates its signals immediately, reflecting the new stage and rendering human gate cards without waiting for the next polling interval
