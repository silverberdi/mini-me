## Context

See `proposal.md` for the production symptom and scope. Today proposal-review escalation builds a generic question from the review summary and passes only that question and reviewer options to the current human-gate recorder. The recorder already persists arbitrary sanitized payload fields. The Trabajo actual panel reads the active payload and renders its question, options, and response form. The existing accepted-response route clears/resumes the gate and must remain authoritative.

## Goals / Non-Goals

**Goals:**
- Carry the reviewer finding data that already exists at escalation into the active gate and make it understandable at the point where the operator responds.
- Keep original review evidence, human authorization, and existing run continuity intact.
- Keep the visible message concise and in simple Spanish, while displaying source fields as evidence.

**Non-Goals:**
- Change reviewer verdict parsing, review criteria, attempt limits, or automatic retry behavior.
- Change proposal contents or financial/data-filtering logic from Issue #238.
- Add a new gate, response endpoint, decision state, or human-inbox redesign.
- Treat an operator response as approval or permission to bypass independent review.

## Decisions

1. **Extend the existing active payload at proposal-review escalation.** Pass the available structured findings and original reviewer summary into the existing gate recorder, where the normal secret sanitization continues to apply. Keep `question` as a short Spanish prompt that states the stop reason and requested operator decision. This reuses the current durable payload and projection instead of adding storage or a parallel review channel.

2. **Present structured evidence separately from the concise question.** The panel should render available severity, location, affected requirement, and expected correction, plus the original reviewer wording clearly marked as evidence. Omit absent/empty fields rather than inventing details. Explain the finding's significance only from the available reviewer content; do not assert an unverified financial impact as fact.

3. **Preserve native choices and label generated choices.** Keep reviewer/workflow options verbatim and identify their source. If none exist, show system-generated alternatives with consequences only when they can be grounded in the current finding and existing authorized response semantics. If no safe discrete alternatives exist, make clear that the operator can answer in free text. Do not add a choice that directly approves the proposal or skips review.

4. **Keep response handling unchanged.** Submit the operator's text through the existing authorized response path. The coordinator continues from its existing proposal-review checkpoint; approval still requires a subsequent independent reviewer approval. This avoids a new authorization shortcut.

Alternatives considered: changing only the generic question would continue to hide reviewer evidence; adding a separate findings endpoint or persisted entity would duplicate the active payload; automatically choosing a correction would remove the required human decision. The existing payload and response flow are sufficient.

## Risks / Trade-offs

- **Reviewer fields may be incomplete or contain sensitive text** → Render only fields that are present, pass the payload through existing secret redaction, and preserve original text as labeled evidence rather than treating it as verified fact.
- **Generated choices could imply approval authority** → Prefer native choices; label generated alternatives and consequences; offer free text when no safe choices exist; never allow a response alone to approve or bypass independent review.
- **Long findings can make the gate difficult to scan** → Keep the question concise and display structured fields in a compact evidence section without discarding them from the payload.
