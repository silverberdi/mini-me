## Why

The Dashboard currently replaces the DeepSeek gauge with plain text when it has a monetary balance. Operators need that balance inside the same shared gauge presentation used by the other providers, while keeping the value truthful when no percentage is available.

## What Changes

- Keep the shared analog-gauge structure visible when `textValue` is supplied.
- Render the observed balance in the gauge center and leave its arc neutral when no verified percentage exists.
- Preserve the existing percentage rendering for providers with a verified percentage.

## Capabilities

### New Capabilities

### Modified Capabilities
- `pwa-capacity-cards-and-reactive-state`: a monetary DeepSeek balance is displayed within the shared gauge rather than replacing it.

## Impact

Frontend `app-analog-gauge` template and its focused unit and Playwright coverage. No API, quota polling, telemetry, or budget behavior changes.
