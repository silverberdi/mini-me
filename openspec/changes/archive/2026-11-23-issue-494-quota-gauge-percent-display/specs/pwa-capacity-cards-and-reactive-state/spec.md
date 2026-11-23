## MODIFIED Requirements

### Requirement: Compact capacity cards
The PWA SHALL display each verified provider/model capacity in the same compact, accessible analog-gauge card structure, with its active model, primary value, status (`Normal`, `En ventana`, or `Crítico`), reset time when known, and an explicit unknown state when not verified. A finite provider-reported `remaining_percent` SHALL control both the gauge arc and the central percentage value. If no verified percentage exists but a verified USD balance does, the card SHALL calculate `balance / 20 * 100`, clamp the displayed projected percentage and arc to 0–100%, and show that projected percentage as the central value. The actual balance and the explicit visual-only nature of the USD 20 reference SHALL remain available in the card's secondary detail. A balance in another currency SHALL NOT be converted into a percentage without a defined reference; it may appear only as secondary detail with a neutral central value and arc. When neither a verified percentage nor a supported USD balance exists, the gauge SHALL show an explicit unknown value and neutral arc. All four provider cards SHALL use the same shared gauge structure and precedence rules; provider-specific data acquisition SHALL NOT create provider-specific rendering branches.

#### Scenario: Provider-reported percentage is the primary value
- **WHEN** a verified observation includes a finite `remaining_percent`
- **THEN** the center displays that percentage with a percent sign
- **AND** the arc represents the same percentage
- **AND** any balance remains secondary detail

#### Scenario: Responsive verified provider percentage
- **WHEN** a verified provider observation includes a finite `remaining_percent` on desktop or mobile
- **THEN** the card presents its provider/model, reported remaining percentage, status, and reset countdown when known within the shared analog-gauge structure
- **AND** the reported percentage controls the arc even when a monetary balance is also present

#### Scenario: Responsive verified quota card
- **WHEN** a verified five-hour observation is available on desktop or mobile
- **THEN** the card presents its provider/model, primary percentage when available, status, and reset countdown within the shared analog-gauge structure

#### Scenario: USD balance projects to a central percentage
- **WHEN** a verified observation has `balance: 10.00`, `currency: USD`, and `remaining_percent: null`
- **THEN** the center displays `50%`
- **AND** the arc represents 50%
- **AND** the actual `$10.00 USD` balance remains secondary detail
- **AND** the detail identifies USD 20 as a visual reference, not provider-reported quota or a spending limit

#### Scenario: USD balance maps to visual progress when percentage is absent
- **WHEN** a verified observation has `balance: 10.00`, `currency: USD`, and `remaining_percent: null`
- **THEN** the card visibly presents `50%` in the center of the shared gauge
- **AND** the gauge arc represents 50% progress
- **AND** the actual balance and USD 20 visual 100% reference appear in secondary detail

#### Scenario: Verified monetary balance is the primary DeepSeek value
- **WHEN** a verified DeepSeek observation contains `balance: 20.18`, `currency: USD`, and `remaining_percent: null`
- **THEN** the capacity card displays a projected percentage in the center of its gauge
- **AND** it presents the actual `$20.18 USD` only in secondary detail

#### Scenario: Projected percentage is consistent and clamped
- **WHEN** a verified observation has a USD balance greater than or equal to 20 and no verified percentage
- **THEN** the center displays at most `100%`
- **AND** the arc is full and does not exceed 100%
- **AND** the actual observed balance remains unchanged in secondary detail

#### Scenario: USD balance at or above the visual reference
- **WHEN** a verified observation has a USD balance of 20.00 or more and no verified percentage
- **THEN** the card presents at most `100%` in its center
- **AND** the gauge arc is full but does not exceed 100%
- **AND** the actual balance in secondary detail is not clamped or altered

#### Scenario: Monetary balance does not invent a gauge denominator
- **WHEN** DeepSeek reports a USD balance without a provider-reported maximum limit or verified percentage
- **THEN** the card uses only the explicitly agreed USD 20 display reference for its projected percentage
- **AND** it identifies the reference as visual only, not as a provider limit or spending policy
- **AND** it does not infer a provider quota or alter the actual balance

#### Scenario: Zero USD balance
- **WHEN** a verified observation has `balance: 0.00`, `currency: USD`, and no verified percentage
- **THEN** the center displays `0%`
- **AND** the arc is empty
- **AND** the actual `$0.00 USD` balance remains in secondary detail

#### Scenario: Other currencies do not use the USD reference
- **WHEN** a verified observation has a monetary balance in a currency other than USD and no verified percentage
- **THEN** the card presents the actual balance and currency only in secondary detail
- **AND** the gauge center and arc remain neutral because no visual reference for that currency is defined

#### Scenario: Unsupported currency does not invent a percentage
- **WHEN** a verified observation has a monetary balance in a currency other than USD and no verified percentage
- **THEN** the balance and currency may appear in secondary detail
- **AND** the center and arc remain neutral/unknown

#### Scenario: Unknown capacity is consistent
- **WHEN** neither a verified percentage nor a supported USD balance is available
- **THEN** every provider card shows the same unknown central value and neutral arc

#### Scenario: Unknown quota is truthful
- **WHEN** no verified capacity observation is available
- **THEN** the card displays an unavailable/unknown state and no fabricated percentage, balance, or reset countdown

#### Scenario: Unknown quota is truthful and consistent
- **WHEN** no verified percentage or supported monetary balance is available
- **THEN** each provider card displays the same unknown value and neutral gauge treatment
- **AND** it shows no fabricated balance or progress

#### Scenario: Missing monetary balance remains truthful
- **WHEN** a DeepSeek observation has no verified `balance` and no verified `remaining_percent`
- **THEN** the card displays an explicit unavailable/unknown state and does not invent a monetary value, percentage, or maximum

#### Scenario: Shared percentage presentation works on mobile
- **WHEN** provider capacity cards render at mobile and desktop viewport sizes
- **THEN** the central percentage remains readable without horizontal overflow
- **AND** the secondary balance/reference detail remains accessible without relying on hover

#### Scenario: Balance remains legible without hover
- **WHEN** a verified monetary balance is displayed on desktop, touch, or mobile
- **THEN** the balance, currency, and projection explanation are readable in secondary detail without requiring a mouse hover

#### Scenario: Shared gauge remains usable on mobile
- **WHEN** the Dashboard displays provider capacity cards on a mobile viewport
- **THEN** all four cards retain the same gauge dimensions and readable primary percentages without horizontal overflow
