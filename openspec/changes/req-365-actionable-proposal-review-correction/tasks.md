## 1. Build evidence-derived correction guidance

- [x] 1.1 Trace the existing exhausted proposal-review payload, reviewer finding shape, and response path; reuse the archived #300 gate behavior without duplicating it.
- [x] 1.2 Compose a complete directive from every actionable finding's non-empty `expected_correction` in reviewer order, retaining enough location/requirement context to identify each correction.
- [x] 1.3 Preserve reviewer-native options verbatim and add the generated system suggestion only as a clearly labeled separate option; when a complete directive cannot be composed, offer free text without inventing a correction.

## 2. Carry the selected directive into native Propose

- [x] 2.1 Project the complete generated directive in the current human gate while keeping its selectable label concise.
- [x] 2.2 Make selecting the generated option populate the clarification field with its full response text; preserve existing selection behavior for native options and free text.
- [x] 2.3 Reuse the current accepted-response and `pending_proposal_revision` path so the exact operator response reaches native OpenSpec Propose on the same Run and Change and the independent review runs again.

## 3. Focused verification without a live project Run

- [x] 3.1 Add coordinator tests for multiple findings, ordering, incomplete corrections, generic-option retirement, and preservation of reviewer-native options.
- [x] 3.2 Add frontend tests proving the full directive is visible and selecting it fills the clarification with the exact response text.
- [x] 3.3 Run the relevant unit/frontend suites and strict OpenSpec validation; confirm no response is treated as review approval or bypasses independent review.

## 4. Final-batch Run evidence

- [ ] 4.1 **Diferida hasta la ronda final de verificación.** With the other authorized Issues implemented, exercise one real active Run from exhausted proposal-review gate through accepted correction, native OpenSpec Propose invocation, and a subsequent independent review. Record the same Run/Change identity and observable invocation/result; do not start a Run for this task before that final batch.
