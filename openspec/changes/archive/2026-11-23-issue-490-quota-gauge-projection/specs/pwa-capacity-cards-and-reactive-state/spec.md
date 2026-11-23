## MODIFIED Requirements

### Requirement: Compact capacity cards
The PWA SHALL display each verified provider/model capacity in the same compact, accessible analog-gauge card structure, with its active model, observed value, status (`Normal`, `En ventana`, or `Crítico`), reset time when known, and an explicit unknown state when not verified. A verified provider-reported `remaining_percent` SHALL control the gauge arc and retain the current percentage presentation. When a verified monetary `balance` and `currency` exist without a verified `remaining_percent`, the card SHALL show the actual balance and currency as its primary center value. For a USD balance, the gauge SHALL use USD 20 as a visual reference equal to 100%, computing `balance / 20 * 100` and clamping only the arc to the range 0–100%. The UI SHALL visibly identify this USD 20 reference as a display scale, not provider-reported quota, spending limit, budget, or authorization. A monetary balance in another currency SHALL remain visible but SHALL NOT be converted to a progress value without a defined reference. When neither a verified percentage nor a supported balance is available, the gauge SHALL show an explicit unknown value and a neutral arc. All four provider cards SHALL use the same shared gauge structure and the same precedence rules; provider-specific data acquisition SHALL NOT create provider-specific rendering branches.

#### Scenario: Responsive verified provider percentage
- **WHEN** a verified provider observation includes a finite `remaining_percent` on desktop or mobile
- **THEN** the card presents its provider/model, reported remaining percentage, status, and reset countdown when known within the shared analog-gauge structure
- **AND** the reported percentage controls the arc even when a monetary balance is also present

#### Scenario: Responsive verified quota card
- **WHEN** a verified five-hour observation is available on desktop or mobile
- **THEN** the card presents its provider/model, real remaining value, status, and reset countdown within the shared analog-gauge structure

#### Scenario: Unknown quota is truthful
- **WHEN** no verified capacity observation is available
- **THEN** the card displays an unavailable/unknown state and no fabricated percentage, balance, or reset countdown

#### Scenario: USD balance maps to visual progress when percentage is absent
- **WHEN** a verified observation has `balance: 10.00`, `currency: USD`, and `remaining_percent: null`
- **THEN** the card visibly presents `$10.00 USD` in the center of the shared gauge
- **AND** the gauge arc represents 50% progress
- **AND** the UI identifies USD 20 as the visual 100% reference

#### Scenario: Verified monetary balance is the primary DeepSeek value
- **WHEN** a verified DeepSeek observation contains `balance: 20.18`, `currency: USD`, and `remaining_percent: null`
- **THEN** the capacity card visibly presents `$20.18 USD` in the center of its gauge
- **AND** it does not present `—` or a percentage in place of that balance

#### Scenario: USD balance at or above the visual reference
- **WHEN** a verified observation has a USD balance of 20.00 or more and no verified percentage
- **THEN** the card presents the exact reported monetary balance in its center
- **AND** the gauge arc is full but does not exceed 100%
- **AND** the balance text is not clamped or altered

#### Scenario: Monetary balance does not invent a gauge denominator
- **WHEN** DeepSeek reports a USD balance without a provider-reported maximum limit or verified percentage
- **THEN** the card uses only the explicitly agreed USD 20 display reference for the arc
- **AND** it identifies the reference as visual only, not as a provider limit or spending policy
- **AND** it does not infer a provider quota or alter the actual balance

#### Scenario: Zero USD balance
- **WHEN** a verified observation has `balance: 0.00`, `currency: USD`, and no verified percentage
- **THEN** the card presents `$0.00 USD`
- **AND** the gauge arc shows 0% progress

#### Scenario: Other currencies do not use the USD reference
- **WHEN** a verified observation has a monetary balance in a currency other than USD and no verified percentage
- **THEN** the card presents the actual balance and currency
- **AND** the gauge arc remains neutral because no visual reference for that currency is defined

#### Scenario: Balance remains legible without hover
- **WHEN** a verified monetary balance is displayed on desktop, touch, or mobile
- **THEN** the balance and currency are readable directly inside the capacity card without requiring a mouse hover

#### Scenario: Unknown quota is truthful and consistent
- **WHEN** no verified percentage or supported monetary balance is available
- **THEN** each provider card displays the same unknown value and neutral gauge treatment
- **AND** it shows no fabricated balance or progress

#### Scenario: Missing monetary balance remains truthful
- **WHEN** a DeepSeek observation has no verified `balance` and no verified `remaining_percent`
- **THEN** the card displays an explicit unavailable/unknown state and does not invent a monetary value, percentage, or maximum

#### Scenario: Shared gauge remains usable on mobile
- **WHEN** the Dashboard displays provider capacity cards on a mobile viewport
- **THEN** all four cards retain the same gauge dimensions and readable primary values without horizontal overflow
