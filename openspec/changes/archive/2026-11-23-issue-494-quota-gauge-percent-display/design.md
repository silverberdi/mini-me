## Context

Issue #490 correctly introduced a shared projection and a USD 20 visual reference, but its acceptance text incorrectly required the monetary balance in the gauge center. The current Dashboard already computes a percentage for the arc while `capacityTextValue()` overrides the center with `$x USD`, creating the mismatch reported by the operator.

## Goals / Non-Goals

**Goals:** make the center and arc show the same percentage; preserve actual source balance and explain the visual projection; retain one shared rendering path.

**Non-Goals:** change provider API calls, OpenCode, telemetry, polling, budgets, spending policy, or deployment.

## Decisions

- Keep `capacityGaugeValue()` as the shared source of the numeric value: verified provider percentage first, otherwise verified USD balance projected against 20.
- For USD fallback, format the same clamped projected value as the central text; never substitute the monetary amount for the percentage.
- Keep the exact monetary balance and the visual-reference explanation in secondary detail so the percentage cannot be mistaken for provider-reported telemetry.
- Leave unknown and unsupported-currency cases neutral; do not fabricate a denominator.
- Verify both central text and the progress arc in focused component and Playwright tests, including mobile visibility.

## Risks / Trade-offs

The USD 20 reference remains a display scale rather than a provider quota. The UI must label the derived value accordingly in secondary detail and preserve the unmodified observed amount there.
