## Context

See `proposal.md` for motivation. The existing backend already returns different truthful fields from each provider: OpenRouter computes `remaining_percent` from its reported credit total and usage, while DeepSeek reports `balance` and leaves `remaining_percent` null. The frontend already uses `app-analog-gauge` for all four cards, but its capacity projection is provider-specific and gives DeepSeek a text value without arc progress.

## Goals / Non-Goals

**Goals:**
- Reuse the existing OpenRouter gauge behavior as a regression control.
- Apply one frontend projection rule across the four provider cards: verified percentage first, otherwise a supported USD balance scale, otherwise unknown.
- Make the visual USD 20 reference understandable without hover and keep the actual balance exact.

**Non-Goals:**
- Changing the provider APIs, OpenCode use, telemetry cadence, backend calculations, or monetary balances.
- Treating USD 20 as a real provider limit, spending cap, authorization, or policy.
- Introducing a new gauge component or general currency conversion system.

## Decisions

1. **Keep `app-analog-gauge` as the only card renderer.** OpenRouter is the presentation control because it already receives a provider-derived percentage and displays progress correctly. Reuse that shared structure rather than adding a second DeepSeek template or component.
2. **Centralize the value precedence in the dashboard projection.** A finite provider-reported `remaining_percent` wins. Otherwise a finite balance with USD uses `balance / 20 * 100` for the arc and the exact balance string for the center. Other currencies can show their balance but remain neutral until a reference is defined. Missing values stay unknown. The arc component clamps progress; the source balance is never changed.
3. **Disclose the USD scale visibly.** Add one concise note near the capacity heading explaining that USD 20 equals 100% only for the visual arc when the provider supplies no percentage. Do not rely on the hover tooltip for this clarification.
4. **Preserve provider telemetry as source of truth.** Do not change DeepSeek or OpenRouter adapters: OpenRouter's actual calculated percentage and DeepSeek's reported balance remain intact. The visual scale is a frontend display convention explicitly supplied by the operator.

## Risks / Trade-offs

- **A visual reference could be mistaken for an actual provider quota** → Keep the actual balance as the center value and display the USD 20 reference beside the section; do not call it a provider limit or budget.
- **Provider percentage and balance may disagree due to different provider semantics** → Prefer the provider-reported percentage when present and use balance scaling only when that field is absent.
- **Balances above USD 20 exceed the arc's representable range** → Clamp the arc at 100% while preserving the exact monetary text.

## Migration Plan

No data or API migration is needed. Update the shared frontend projection and focused tests; CI's frontend build and Playwright validation exercise the candidate. Revert the frontend change if validation fails.
