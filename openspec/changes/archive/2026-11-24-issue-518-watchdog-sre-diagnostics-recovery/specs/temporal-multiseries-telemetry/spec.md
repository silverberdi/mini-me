## MODIFIED Requirements

### Requirement: Continuous autonomy and active machine time
The system SHALL calculate the autonomy dimension as a bounded temporal aggregate percentage of eligible completed runs that finished without operator intervention. A completed run SHALL count as autonomous when authoritative persisted evidence shows that no operator action or human-gate response was required; successful deterministic Watchdog remediation remains autonomous. The denominator SHALL include only completed runs with complete, unambiguous evidence for that classification. Incomplete, failed, cancelled, or evidence-ambiguous runs SHALL NOT be silently classified as autonomous or operator-assisted. Buckets with no eligible observations SHALL return explicit no-data, not zero or a fabricated percentage. Technical retries, loops, and rescue evidence MAY be reported separately but SHALL NOT be blended into this aggregate as a synthetic per-run score. Legitimate human governance gates SHALL remain distinct from technical recovery. The delivery-time dimension SHALL report active machine processing duration from recorded execution intervals and SHALL exclude human-gate waiting intervals.

#### Scenario: Aggregate autonomy uses completed-run evidence
- **WHEN** a time bucket contains completed runs with complete evidence of whether an operator action was required
- **THEN** the autonomy percentage is the count completed without operator intervention divided by the eligible completed-run count
- **AND** a run successfully recovered by an eligible Watchdog playbook counts as autonomous if no operator action was required

#### Scenario: Human gate response counts as operator intervention
- **WHEN** a completed run required an operator to answer a human gate
- **THEN** that run contributes to the eligible denominator and the operator-assisted count
- **AND** a governance wait is not mislabeled as a technical failure or retry

#### Scenario: Missing outcome evidence is not fabricated
- **WHEN** a run is incomplete, failed, cancelled, or lacks unambiguous intervention evidence
- **THEN** it is excluded from the autonomy numerator and denominator
- **AND** a bucket with no eligible completed runs is represented as no-data

#### Scenario: Retries and active machine time remain distinct
- **WHEN** a completed run contains retries or same-work loops and has recorded machine-processing and human-wait intervals
- **THEN** retries and loops remain separately identifiable evidence rather than a fabricated per-run autonomy percentage
- **AND** active machine time sums only machine-processing intervals and excludes human-gate waits

#### Scenario: Retries lower autonomy without binary collapse
- **WHEN** two time buckets have comparable completed-run counts and operator-intervention rates, but one has more technical retries or same-work loops
- **THEN** the autonomy percentage remains the observed share of completed runs without operator intervention
- **AND** retry and loop evidence remains separately visible and is not converted into a fabricated per-run 0% or 100% value

#### Scenario: Active machine time excludes human waits
- **WHEN** a run has recorded machine-processing intervals and one or more human-gate waiting intervals
- **THEN** its delivery-time observation sums only machine-processing intervals
- **AND** the human-gate waiting intervals are excluded and remain identifiable as excluded waits
