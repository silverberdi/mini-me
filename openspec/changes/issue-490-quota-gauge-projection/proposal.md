## Why

DeepSeek provides a verified USD balance without a provider percentage, while OpenRouter provides a verified percentage derived from its credit totals. The shared gauge currently leaves DeepSeek's arc empty despite showing its balance, so the operator cannot read remaining capacity consistently.

## What Changes

- Use the existing OpenRouter gauge presentation as the control: provider data flows through one shared projection and one gauge structure.
- Prefer a provider-reported remaining percentage; when it is absent and a verified USD balance exists, derive only the visual arc from the agreed reference USD 20 = 100%.
- Keep the actual balance as the center label, clamp only the visual arc to 0–100%, and explain the reference visibly.
- Preserve the neutral unknown state when neither a verified percentage nor supported USD balance is available.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `pwa-capacity-cards-and-reactive-state`: unify the four provider cards' capacity projection and define the USD balance reference used only for visual gauge progress.

## Impact

- Frontend dashboard projection and its existing shared analog gauge.
- Focused dashboard unit and Playwright coverage.
- No provider API, OpenCode invocation, backend polling, stored data, or spending policy changes.
