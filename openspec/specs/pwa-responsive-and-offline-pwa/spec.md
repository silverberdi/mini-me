# pwa-responsive-and-offline-pwa Specification

## Purpose
TBD - created by archiving change 017-pwa-control-center. Update Purpose after archive.

## Requirements

### Requirement: Multi-Breakpoint Responsive Layout
The system SHALL support Desktop Standard (~1366x768), Large Desktop / Ultrawide (>=1920px), Tablet (~1024x768), and Mobile (~390x844) viewports without horizontal scrolling, clipped content, or dead layout areas.

#### Scenario: View PWA on ultrawide desktop
Given a browser viewport width of 2560px
When the PWA Control Center loads
Then the layout SHALL render in a 3-column split view utilizing full available width for Queue, Pipeline Stepper, and Candidate Inspector without excessive blank margins.

#### Scenario: View PWA on mobile device
Given a browser viewport width of 390px
When the PWA Control Center loads
Then the layout SHALL collapse into a single-column view with sticky top header, touch-friendly navigation tabs, and full-screen modal sheets for deep inspections.

### Requirement: W3C Web App Manifest and PWA Installability
The system SHALL provide a valid W3C Web App Manifest (`manifest.webmanifest`) specifying application name, short name, start URL, standalone display mode, background color, theme color, and multi-resolution icons (`192x192`, `512x512`), enabling browser installation as a standalone app.

#### Scenario: Install PWA Control Center
Given a modern web browser visiting the root URL
When the browser checks PWA installability requirements
Then the manifest SHALL validate successfully and provide standalone display mode metadata.

### Requirement: Service Worker Static Shell Caching and Offline Resilience
The system SHALL register a Service Worker (`sw.js`) that caches all core application shell assets (HTML, CSS, JS, manifest, icons) using a stale-while-revalidate strategy, and provides a degraded offline banner when backend APIs are unreachable.

#### Scenario: Backend disconnection handling
Given the PWA Control Center is loaded and the backend service becomes unreachable
When the next polling cycle fails
Then the PWA shell SHALL remain functional and display a `Backend Disconnected — Retrying...` status banner without crashing or showing a blank page.

#### Scenario: Automatic reconnection recovery
Given the PWA is currently displaying the disconnected status banner
When backend connectivity is restored
Then the banner SHALL clear automatically and resume live telemetry updates.
