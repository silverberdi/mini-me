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
The system SHALL calculate the autonomy dimension as a bounded temporal aggregate percentage of eligible completed runs using the proportion of traversed stages completed autonomously, while retaining the existing completed-run evidence boundary. A stage SHALL count as autonomous only when authoritative persisted evidence shows that it completed without operator action, a human-gate response, or a technical blocker; successful deterministic Watchdog remediation SHALL count as autonomous for that stage. A legitimate governance or scope-authorization gate SHALL be classified separately from a technical block or failure and SHALL NOT be represented as an operator-needed technical failure. The denominator SHALL include only completed runs with complete, unambiguous evidence of traversed stages and their outcomes. Incomplete, failed, cancelled, or evidence-ambiguous runs SHALL NOT be silently classified as autonomous or operator-assisted. Buckets with no eligible observations SHALL return explicit no-data, not zero or a fabricated percentage. Technical retries, loops, and rescue evidence MAY be reported separately but SHALL NOT be blended into this stage proportion as a synthetic per-run binary score. The delivery-time dimension SHALL report active machine processing duration from recorded execution intervals and SHALL exclude human-gate waiting intervals.

#### Scenario: Aggregate autonomy uses completed-run stage evidence
- **WHEN** a time bucket contains completed runs with complete evidence of the stages each run traversed and whether each stage completed autonomously
- **THEN** each run's autonomy value is the percentage of its traversed stages completed autonomously
- **AND** the bucket autonomy percentage is the bounded aggregate of those eligible stage proportions
- **AND** a run successfully recovered by an eligible Watchdog playbook counts recovered stages as autonomous if no operator action was required

#### Scenario: Human gate response counts as operator intervention
- **WHEN** a completed run required an operator to answer a human gate for a traversed stage
- **THEN** that stage is not counted in the autonomous numerator
- **AND** the run contributes to the eligible denominator when its stage evidence is complete
- **AND** a governance wait is not mislabeled as a technical failure or retry

#### Scenario: Missing outcome evidence is not fabricated
- **WHEN** a run is incomplete, failed, cancelled, or lacks unambiguous evidence for its traversed stages
- **THEN** it is excluded from the autonomy numerator and denominator
- **AND** a bucket with no eligible completed runs is represented as no-data

#### Scenario: Retries and active machine time remain distinct
- **WHEN** a completed run contains retries or same-work loops and has recorded machine-processing and human-wait intervals
- **THEN** retries and loops remain separately identifiable evidence rather than a fabricated per-run autonomy percentage
- **AND** active machine time sums only machine-processing intervals and excludes human-gate waits

#### Scenario: Retries lower autonomy without binary collapse
- **WHEN** two time buckets have comparable completed-run counts and operator-intervention rates, but one has more technical retries or same-work loops
- **THEN** the autonomy percentage remains the observed aggregate of eligible traversed-stage proportions
- **AND** retry and loop evidence remains separately visible and is not converted into a fabricated per-run 0% or 100% value

#### Scenario: Active machine time excludes human waits
- **WHEN** a run has recorded machine-processing intervals and one or more human-gate waiting intervals
- **THEN** its delivery-time observation sums only machine-processing intervals
- **AND** the human-gate waiting intervals are excluded and remain identifiable as excluded waits

#### Scenario: Governance gate is distinct from technical blocking
- **WHEN** a completed run traversed six stages, one stage records a proposal governance authorization, and the other five stages completed autonomously
- **THEN** the run autonomy value is at least 80 percent and is not 0 percent
- **AND** the projection labels the governance authorization separately from a technical block or failure

### Requirement: Autonomy intervention outcome visibility
The autonomy projection SHALL distinguish eligible completed Runs and their traversed-stage outcomes across clean autonomous execution, autonomous SRE recovery, governance authorization, technical blocking or failure, and operator action. It SHALL derive these categories only from complete, immutable intervention, stage, gate, and operator-action evidence linked to the Run; successful autonomous recovery SHALL remain autonomous in the aggregate. Incomplete or contradictory evidence SHALL be excluded from classification and surfaced as unverified/no-data rather than guessed.

#### Scenario: Clean run and autonomous recovery are distinguished
- **WHEN** completed Runs have evidence respectively showing no intervention and a successful autonomous SRE intervention with no operator action
- **THEN** the projection exposes separate counts for clean completion and autonomous recovery
- **AND** both remain in the autonomous share under the existing autonomy definition

#### Scenario: Operator-needed run is identified
- **WHEN** a completed Run has evidence of operator action or a human-gate response for a non-governance technical block
- **THEN** the projection identifies the affected stage as requiring operator action
- **AND** includes its non-autonomous stage outcome in the eligible completed-run projection

#### Scenario: Intervention evidence is missing or contradictory
- **WHEN** a Run has an intervention record without a conclusive result, or its intervention and operator-action evidence conflict
- **THEN** the projection excludes it from the outcome categories and autonomy percentage
- **AND** reports it as unverified rather than inferring success or autonomy

#### Scenario: Governance authorization is visible independently
- **WHEN** a Run has a resolved proposal or scope-authorization gate and complete evidence for all later autonomous stages
- **THEN** the projection reports the governance authorization as its own outcome
- **AND** does not classify that authorization as a technical block or as an all-or-nothing operator-needed Run

### Requirement: Proportional autonomy projection preserves bounded evidence
The system SHALL expose enough per-point autonomy evidence to explain the numerator, denominator, and distinct governance/technical outcomes used for each temporal bucket, SHALL bound the resulting percentage to 0 through 100, and SHALL preserve explicit no-data for buckets without eligible stage evidence.

#### Scenario: Point explains proportional autonomy
- **WHEN** a project bucket contains two eligible completed Runs with stage proportions of 5/6 and 4/4
- **THEN** the point value is the documented aggregate of those proportions
- **AND** its evidence reports the eligible stage/run counts and governance outcome count
- **AND** the value is between 0 and 100 inclusive

#### Scenario: No eligible stage evidence remains no-data
- **WHEN** all completed Runs in a bucket lack complete traversed-stage evidence
- **THEN** the bucket is marked no-data
- **AND** the projection does not substitute 0 percent

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
