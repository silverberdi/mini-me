## ADDED Requirements

### Requirement: Apply preserves validation disposition and evidence provenance
Apply and Verify SHALL interpret validation tasks according to the strictly validated, currently active OpenSpec Change. A task explicitly deferred by an operator-authorized native Update SHALL remain visibly deferred or pending and SHALL NOT be marked complete without its required evidence. Evidence reported for a published version SHALL retain that source identity and SHALL NOT satisfy a candidate-specific criterion unless its immutable SHA is proven to match the candidate under review. Apply MAY continue with other work only when the updated Change permits it; Verify and PR readiness SHALL follow the updated acceptance criteria and fail closed when required evidence remains absent.

#### Scenario: Published-version evidence is not attributed to the candidate
- **GIVEN** the operator reports a validation performed on a published version
- **AND** that version's immutable SHA is absent or differs from the candidate SHA
- **WHEN** the coordinator records and evaluates the evidence
- **THEN** it identifies the evidence as belonging to the published version
- **AND** does not mark a candidate-specific task complete or claim candidate validation
- **AND** identifies the candidate evidence still required.

#### Scenario: Deferred criterion remains distinct from completed work
- **GIVEN** the operator-authorized OpenSpec Update explicitly defers a validation criterion
- **WHEN** native Apply processes the updated Change
- **THEN** it preserves the criterion's deferred/pending disposition and continues only with remaining work allowed by the updated Change
- **AND** it does not count the criterion as completed or as Apply progress
- **AND** Verify or PR preparation remains blocked if the updated acceptance criteria still require that evidence.

#### Scenario: No safe continuation from updated criteria
- **GIVEN** updated artifacts are invalid, ambiguous about whether deferred evidence gates completion, or inconsistent with the operator's explicit decision
- **WHEN** Apply or Verify evaluates readiness
- **THEN** it preserves the candidate and evidence and reports the exact unresolved criterion
- **AND** does not silently drop the criterion, mark it complete, or spend another Apply attempt on a generic retry.
