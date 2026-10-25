---
name: minime-request-normalizer
description: Convert one remote Request into faithful, complete Gherkin before OpenSpec Explore.
version: "1.0.0"
---

# Request normalization

Read the Request, comments and attached source references in the authorized
context. Produce exactly the structured response requested by the coordinator:
`normalized_body` and `criteria`.

Preserve every stated fact and acceptance criterion. Rephrase for complete
Given/When/Then scenarios, but do not invent requirements, decisions, tasks,
business rules or operational backlog items. If material meaning is ambiguous,
keep the ambiguity explicit in the scenario and evidence; do not resolve it by
guessing. This skill provides semantic content only. GitHub comments, Issue
updates, concurrency, identity and remote confirmation remain adapter duties.
