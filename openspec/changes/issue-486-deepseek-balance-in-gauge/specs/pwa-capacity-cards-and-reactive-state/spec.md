## MODIFIED Requirements

### Requirement: Compact capacity cards
The PWA SHALL display each verified provider/model capacity in the same compact, accessible analog-gauge card structure, with its active model, observed value, status (`Normal`, `En ventana`, or `Crítico`), reset time when known, and an explicit unknown state when not verified. When a verified observation provides a finite monetary `balance` and `currency` but no `remaining_percent`, the card SHALL present the monetary balance as its primary visible value with the reported currency inside the gauge, SHALL NOT append `%`, SHALL NOT derive a progress fraction from an invented maximum, and SHALL keep the gauge arc neutral. When a verified percentage is available, the gauge SHALL continue to represent that percentage. The PWA SHALL NOT imply measured progress when no verified percentage exists.

#### Scenario: Responsive verified quota card
- **WHEN** a verified five-hour observation is available on desktop or mobile
- **THEN** the card presents its provider/model, real remaining value, status, and reset countdown within the shared analog-gauge structure

#### Scenario: Unknown quota is truthful
- **WHEN** no verified capacity observation is available
- **THEN** the card displays an unavailable/unknown state and no fabricated percentage, balance, or reset countdown

#### Scenario: Verified monetary balance is the primary DeepSeek value
- **WHEN** a verified DeepSeek observation contains `balance: 20.18`, `currency: USD`, and `remaining_percent: null`
- **THEN** the capacity card visibly presents `$20.18 USD` in the center of its gauge
- **AND** it does not present `—` or a percentage in place of that balance

#### Scenario: Monetary balance does not invent a gauge denominator
- **WHEN** DeepSeek reports a monetary balance without a provider-reported maximum limit or verified percentage
- **THEN** the card presents the balance within the shared gauge structure
- **AND** its gauge arc remains neutral
- **AND** it does not calculate a percentage, artificial maximum, or synthetic progress position

#### Scenario: Balance remains legible without hover
- **WHEN** a verified monetary balance is displayed on desktop, touch, or mobile
- **THEN** the balance and currency are readable directly inside the capacity card without requiring a mouse hover

#### Scenario: Missing monetary balance remains truthful
- **WHEN** a DeepSeek observation has no verified `balance` and no verified `remaining_percent`
- **THEN** the card displays an explicit unavailable/unknown state and does not invent a monetary value, percentage, or maximum
