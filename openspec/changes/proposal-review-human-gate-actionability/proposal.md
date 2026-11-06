## Why

When independent proposal review reaches its attempt ceiling, the current human gate can contain only a vague English summary and no response options, even though the reviewer returned structured findings. The operator cannot identify the affected requirement or make an informed decision, so the run remains blocked without useful guidance.

## What Changes

- Preserve the available structured proposal-review findings in the active human-gate payload when review escalates.
- Present a concise Spanish explanation of what was found, where, why it matters, what correction was requested, and why the workflow stopped; retain the original reviewer wording as identifiable evidence.
- Make the decision required of the operator explicit. Preserve native workflow options when present; when absent, present clearly labeled system-generated alternatives with consequences if they are safe and discrete, otherwise allow a free-text response.
- Keep the existing human gate and authorized response path. A response must not approve the proposal or bypass the required independent review.
- Render the current gate context and response choices in Trabajo actual.

## Capabilities

### New Capabilities

### Modified Capabilities
- `openspec-orchestration-continuity`: proposal-review escalation payloads and their human-facing decision context become actionable while preserving the blocking response workflow.
- `openspec-native-propose`: exhausted independent proposal review exposes its structured findings and required operator decision without changing review verdict or attempt-limit semantics.

## Impact

Expected implementation impact is limited to proposal-review escalation and the existing human-gate projection/rendering path, with focused coordinator/API and frontend coverage. No change is proposed to review criteria, retry limits, OpenSpec workflow invocation, financial calculations, or the broader human-attention inbox.
