---
name: minime-request-normalizer
description: Convert one remote Request into faithful, complete Gherkin before OpenSpec Explore.
version: "1.0.0"
---

# Request normalization

Read the Request, comments and attached source references in the authorized
context. Produce exactly one structured response with these three required fields:
`normalized_body`, `criteria` and `semantic_message`.

`semantic_message` must be a brief, concrete comment in simple Spanish describing the
normalization result. Do not put logs, secrets or a second response object in it.

`normalized_body` must be complete Gherkin in one supported official dialect:
English (default, with `Feature:`, `Scenario:`, `Given`, `When`, `Then`) or Spanish
with `# language: es` (with `Característica:`, `Escenario:`, `Dado`/`Dada`, `Cuando`,
`Entonces`). It must contain at least one Feature, Scenario and each of Given/When/Then
steps. Keep the descriptions in Spanish when the Request is Spanish. The `criteria`
array must preserve every source criterion, including stable identifiers such as C1, C2
and C3. Example:

```gherkin
# language: es
Característica: Ordenación por consola

  Escenario: Conserva los criterios del Request
    Dado un Request con C1, C2 y C3
    Cuando se normaliza antes de Explore
    Entonces cada criterio queda trazable sin inventar requisitos
```

Preserve every stated fact and acceptance criterion. Rephrase for complete
Given/When/Then scenarios, but do not invent requirements, decisions, tasks,
business rules or operational backlog items. If material meaning is ambiguous,
keep the ambiguity explicit in the scenario and evidence; do not resolve it by
guessing. This skill provides semantic content only. GitHub comments, Issue
updates, concurrency, identity and remote confirmation remain adapter duties.
