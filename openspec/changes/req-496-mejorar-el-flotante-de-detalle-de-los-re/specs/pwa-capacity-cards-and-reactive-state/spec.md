# Spec Delta

## ADDED Requirements

### Requirement: Separated and truthful capacity detail floating panel

The PWA SHALL present the available detail for each Codex, Antigravity, DeepSeek, and OpenRouter capacity card in a shared, readable floating panel associated with that card. The panel SHALL be visually separated from the gauge arc, central value, and provider label, and SHALL NOT cover them. Secondary detail currently rendered persistently below a card SHALL be presented inside that card's floating panel instead. The panel SHALL show only values available in the existing provider observation, clearly distinguish provider-reported values from visual projections, and omit unavailable fields rather than inventing data.

#### Scenario: Each provider card exposes its own readable detail

- **GIVEN** the Dashboard displays the four provider capacity cards
- **WHEN** the user points to or focuses any one card
- **THEN** a readable floating panel for that card presents only its corresponding observation details
- **AND** the panel is visually consistent across Codex, Antigravity, DeepSeek, and OpenRouter

#### Scenario: Floating panel does not cover the gauge

- **GIVEN** a capacity card has a visible detail panel
- **WHEN** the panel is displayed above or near the card
- **THEN** the panel remains separated from the arc, central value, and provider label
- **AND** those primary elements remain readable and unobscured

#### Scenario: DeepSeek and OpenRouter secondary detail moves into the panel

- **GIVEN** DeepSeek or OpenRouter has secondary balance or reference detail available
- **WHEN** its capacity card detail is presented
- **THEN** the detail appears inside that provider's floating panel
- **AND** the same detail is not rendered persistently below the card

#### Scenario: Available fields are distinguished without inference

- **GIVEN** an observation may contain a model, reported percentage, observed balance, visual reference, state, source, observation date, or other optional fields
- **WHEN** the floating panel is rendered
- **THEN** it includes only fields present in that observation
- **AND** it labels a visual USD reference as a projection rather than provider-reported data
- **AND** it does not display missing values or estimates as observed provider data

#### Scenario: Existing primary gauge presentation is preserved

- **GIVEN** a capacity card has its current percentage, colors, label, and gauge behavior
- **WHEN** the floating detail presentation is improved
- **THEN** the primary percentage, colors, label, quota logic, and calculations remain unchanged
- **AND** only the detail presentation and its placement are changed

#### Scenario: Detail remains usable at supported responsive sizes

- **GIVEN** the Dashboard is rendered in a real browser at desktop or mobile width
- **WHEN** the user points to or focuses a capacity card
- **THEN** the floating panel remains readable within the viewport without obscuring the card's primary content
- **AND** the card does not require horizontal overflow to expose its primary value or label
