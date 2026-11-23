# temporal-multiseries-telemetry Specification

## Purpose

Define a trustworthy temporal telemetry contract that lets operators compare portfolio and project trends across autonomy, active machine delivery time, and liquidated cost without fabricating missing observations or conflating human waits with processing.

## Requirements

### Requirement: Temporal multi-series telemetry projection
The system SHALL expose a Dashboard telemetry projection over a bounded historical window, defaulting to the latest 30 calendar days, with a common daily or weekly time bucket and the selected operational dimension of autonomy, active machine delivery time, or liquidated cost. The projection SHALL include one prominent `Global (Todos los proyectos)` series and one series for every registered project represented by verifiable observations, with stable project identity and an explicit no-data state when no observation exists for a bucket.

#### Scenario: Global and project trends share a time axis
- **WHEN** the selected window contains verifiable observations for two registered projects across multiple days
- **THEN** the Dashboard returns a common ordered bucket axis
- **AND** returns a Global series aggregated across those projects plus one independently attributable series per project
- **AND** does not place observations on unrelated run-order positions or an invented bucket

#### Scenario: Empty or incomplete historical data
- **WHEN** the selected window has no verifiable observations for a dimension or a bucket has no observation for a represented project
- **THEN** the projection identifies the dimension or bucket as having no data
- **AND** does not substitute zero, a fabricated percentage, an estimated cost, or a repeated last value

### Requirement: Continuous autonomy and active machine time
The system SHALL calculate autonomy as a bounded continuous index from 0% through 100% using recorded productive progress, technical retries, loops, and convergence rescues. Legitimate human governance gates SHALL remain distinguishable from technical rescue/rework penalties. The delivery-time dimension SHALL report active machine processing duration from recorded execution intervals and SHALL exclude human-gate waiting intervals.

#### Scenario: Retries lower autonomy without binary collapse
- **WHEN** two otherwise comparable project histories contain productive progress, with one history including technical retries or same-work loops
- **THEN** the history with technical rework receives a lower continuous autonomy index
- **AND** both indices remain within 0% and 100%
- **AND** a legitimate human governance wait alone does not count as a technical rescue

#### Scenario: Active machine time excludes human waits
- **WHEN** a run has recorded machine-processing intervals and one or more human-gate waiting intervals
- **THEN** its delivery-time observation sums only machine-processing intervals
- **AND** the human-gate waiting intervals are excluded and remain identifiable as excluded waits

### Requirement: Interactive series visibility and isolation
The Dashboard SHALL provide an interactive legend for every visible Global or project series in each of the three dimensions. The operator SHALL be able to toggle any individual series, activate `Aislar`/Solo for exactly one selected series, restore the complete selection, and hover a legend chip or line so non-focused series are visibly attenuated without being removed from context.

#### Scenario: Toggle and Solo preserve series identity
- **WHEN** the operator toggles a project series and then activates `Aislar` for the Global series
- **THEN** the toggled project series becomes hidden
- **AND** only the Global series remains emphasized in Solo mode
- **AND** the legend preserves the identity and available visibility control for every series

#### Scenario: Hover attenuates without mutating selection
- **WHEN** the operator hovers a project line or its legend chip
- **THEN** the hovered series is emphasized and the other rendered series are attenuated
- **AND** the underlying toggle/Solo selection is unchanged when the hover ends

### Requirement: Dimension compatibility and current-work preservation
The Dashboard SHALL apply the same temporal axis, multi-series identity, legend controls, Solo mode, hover attenuation, and no-data semantics when the operator switches among `Calidad / Autonomía`, `Tiempos de Entrega`, and `Costo liquidado`. The change SHALL NOT alter the authoritative data, navigation, or presentation contract of the focalized Trabajo Actual summary.

#### Scenario: All three dimensions retain interaction behavior
- **WHEN** the operator switches through autonomy, active delivery time, and liquidated cost
- **THEN** each dimension renders the Global and project series on the common temporal axis
- **AND** each dimension exposes toggle, Solo, hover attenuation, and explicit no-data behavior

#### Scenario: Trabajo Actual remains focalized
- **WHEN** the operator opens or refreshes the Dashboard while the temporal telemetry projection is loaded
- **THEN** the existing active-work summary continues to show only its authoritative Run/Request/stage information and navigation
- **AND** telemetry loading or interaction does not invent progress, replace its source, or change Trabajo Actual behavior
