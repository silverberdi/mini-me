# Spec Delta

## ADDED Requirements

### Requirement: Liquidated provider cost presentation
The Dashboard SHALL present cost data only from verifiable liquidated entries in the durable PostgreSQL budget ledger, never by deriving a price from run tokens or by substituting synthetic values. Each presented cost point SHALL retain its ledger timestamp, provider identity, model identity when available, and USD amount at the ledger's precision, and SHALL be attributable separately at minimum to DeepSeek Direct and OpenRouter.

#### Scenario: Display settled DeepSeek and OpenRouter costs
- **WHEN** the durable ledger contains liquidated cost entries for DeepSeek Direct and OpenRouter, including provider, model, amount, and timestamps
- **THEN** the Dashboard displays the real USD amounts in separate provider series or groups
- **AND** each displayed amount retains its recorded provider, model when available, timestamp, and ledger-compatible precision

#### Scenario: Preserve model breakdown when recorded
- **WHEN** liquidated ledger entries for one provider contain distinct model identities
- **THEN** the Dashboard keeps those model identities as a visible breakdown
- **AND** it does not merge the entries into an unattributed provider total when the model data is available

#### Scenario: Include verified-provider costs with unidentified models
- **WHEN** a liquidated ledger entry has a verified provider identity but its model is null or not recognized
- **THEN** the Dashboard includes its amount in that provider's total
- **AND** the model breakdown shows the amount under `Modelo no identificado`
- **AND** it does not attribute the amount to a specific model or another provider

#### Scenario: Do not infer a cost from run tokens
- **WHEN** a Run exposes token counts but the durable ledger has no liquidated price for that usage
- **THEN** the Dashboard does not calculate or display a USD cost from those tokens
- **AND** the usage is not attributed to DeepSeek Direct, OpenRouter, or any model by default

#### Scenario: Explicit no-data state
- **WHEN** no verifiable liquidated cost exists for the Dashboard query
- **THEN** the Dashboard cost payload has the structure `{ "status": "no_data", "providers": [], "series": [] }`
- **AND** the cost visualization displays an explicit “sin datos” state
- **AND** it does not display `0`, `CLI`, an estimate, or a provider/model attribution

#### Scenario: Exclude unknown provider identities
- **WHEN** the durable ledger contains an otherwise liquidated entry whose provider identity is unknown to the existing provider catalog
- **THEN** the entry is excluded from the Dashboard cost payload and provider aggregation
- **AND** the Dashboard does not relabel it as DeepSeek Direct, OpenRouter, or another known identity

#### Scenario: Timestamp-backed time series
- **WHEN** the Dashboard renders a time series of liquidated costs
- **THEN** every point is backed by an observable ledger timestamp and a defined aggregation granularity
- **AND** entries without the required verifiable timestamp are not silently assigned to an invented time bucket

#### Scenario: End-to-end ledger-to-dashboard representation
- **WHEN** PostgreSQL contains registered liquidated usage for DeepSeek Direct and OpenRouter
- **THEN** a real end-to-end verification observes the ledger records, invokes the Dashboard read path, and demonstrates the corresponding provider/model costs in the rendered visualization
