# Spec Delta

## MODIFIED Requirements

### Requirement: Multi-Breakpoint Responsive Layout
The system SHALL offer the same five independent Spanish views on desktop, tablet and mobile with light/dark themes, keyboard and screen-reader access, visible focus, adequate contrast, touch targets and zoom/reflow. Desktop SHALL be a readable control center with proportionate scrolling regions; tablet SHALL support master/detail; mobile SHALL navigate focused views/details without horizontal content loss. Only two primary destinations SHALL remain across devices; missing backend authority SHALL remain disabled everywhere. A future Angular + TypeScript + Tailwind frontend SHALL preserve this responsive and accessible behavior before the legacy frontend can be retired. Within the «Trabajo actual» view, the current-work card SHALL place the «Volver a Trabajo» action below its supervision description, keep that action label on one line, and use the former primary visual space for a decorative illustration selected by the selected run's current stage. The card SHALL preserve its current textual stage/status communication, navigation behavior and supported viewport operation, and its redesigned total height SHALL NOT exceed the current card height for the same viewport width and content.

#### Scenario: View PWA on ultrawide desktop
- **WHEN** the application loads in a 2560px-wide viewport
- **THEN** the selected view uses the available width for readable content and contextual detail without horizontal overflow or excessive blank regions, preserving two primary destinations rather than restoring the retired Queue/Pipeline/Inspector composition.

#### Scenario: View PWA on mobile device
- **WHEN** the application loads in a 390px-wide viewport
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

#### Scenario: Reorganized current-work card
- **WHEN** the «Trabajo actual» card is rendered with the same viewport width and content as the current card
- **THEN** «Volver a Trabajo» appears below «Supervisión detallada…», its label remains on one line, the card height does not exceed the current card height, and the navigation action still reaches Trabajo.

#### Scenario: Illustration follows selected run stage
- **WHEN** a selected run has one of ADMITTED, EXPLORING, PROPOSING, PROPOSAL_REVIEW, IMPLEMENTING, RUNNING_TESTS, VERIFYING, CODE_REVIEW, PREPARING_PR or COMPLETED as its current stage
- **THEN** the card displays the exact Issue-approved PNG assigned to that stage, at a coherent size and alignment, with decorative semantics, while the existing textual stage and status remain available.

#### Scenario: Missing or unrecognized stage
- **WHEN** no run is selected or the selected run has an unknown stage
- **THEN** the «Trabajo actual» card remains usable without a broken image, false stage assignment, navigation change or loss of its existing textual state communication.
