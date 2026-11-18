## Context

See `proposal.md` for the operator problem. The existing exhausted-review path in `orchestration_coordinator.py` stores structured findings in the active gate but falls back to one generic option when the reviewer does not provide options. The existing response path accepts the operator clarification, records it, stores `pending_proposal_revision`, and sends that context to the native Propose workflow. The Trabajo actual view displays option labels and descriptions, while selection currently copies the label into the clarification field. The prior archived Change `proposal-review-human-gate-actionability` already added visible finding details; this Change fills the remaining gap in the selectable correction directive and its handoff.

## Goals / Non-Goals

**Goals:**
- Compose one complete correction directive from the current review findings without losing reviewer order or inventing missing corrections.
- Display the complete generated directive while keeping the option label readable.
- Make selection populate the clarification with the exact directive and reuse the existing accepted-response and native Propose continuation path.
- Preserve native reviewer options and require another independent review after Propose.

**Non-Goals:**
- Change reviewer criteria, attempt limits, proposal approval semantics, Run identity, or the OpenSpec workflow.
- Add endpoints, database entities, a prompt-based correction generator, or an additional decision gate.
- Defer or claim completion of any validation criterion without its required evidence.

## Decisions

1. **Compose the directive from structured findings, not another model call.** Use the reviewer-provided `expected_correction` values in their existing order and include enough available finding context (location and affected requirement) to distinguish the items. This keeps the response faithful to the reviewer and avoids new provider cost or invented instructions. If any actionable finding has no concrete correction, do not offer a supposedly complete generated directive; retain free-text response.

2. **Keep the option label concise and carry full text in the existing option payload.** Add an optional response-text value to the system-generated option and show the full directive in its existing description. Update the current option-selection handler to use that response text when present, while preserving its current fallback for native options. Native reviewer options remain verbatim; when a safe generated correction exists, it is offered as a separate, clearly labeled system-generated option rather than rewriting a native choice.

3. **Reuse durable gate and continuation behavior.** Store the generated option with the current human-gate payload, then let the existing response endpoint persist the selected text and resume the same Run/Change through native Propose. Do not add another persistence model or bypass the second independent review. Focus tests on composition, UI selection, and continuation-context fidelity; any scenario that requires a real active project Run remains deferred to the final validation batch requested by the operator.

## Risks / Trade-offs

- **[Risk] A complete directive can be long when several findings exist.** → Preserve all correction text rather than truncating it; keep the clickable label short and show the full text in the option description and selected clarification.
- **[Risk] A reviewer finding may be substantive but omit `expected_correction`.** → Do not guess; offer the preserved findings and free-text response instead.
- **[Risk] Native options and the generated suggestion could be confused.** → Preserve native text and label the generated alternative as a system suggestion with its consequences.

## Migration Plan

No database migration is expected because the active gate already stores option payloads and accepted clarification text. Roll back through the normal code release if the generated alternative is malformed; the existing free-text and native-option paths remain available.
