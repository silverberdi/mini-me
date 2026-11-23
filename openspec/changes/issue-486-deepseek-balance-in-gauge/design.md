## Context

`app-analog-gauge` already renders the shared gauge used by all four provider cards. Its `textValue` branch currently replaces the entire gauge SVG, which makes DeepSeek visually different when it has a balance but no percentage. See the proposal and delta spec for the intended behavior.

## Goals / Non-Goals

**Goals:** Keep one gauge structure and render the balance in its center. With no verified percentage, show only the neutral arc; preserve percentage-based rendering otherwise.

**Non-Goals:** Change quota sources, polling, data contracts, other providers' values, or invent progress from the monetary balance.

## Decisions

- Keep the existing gauge SVG and card layout rendered regardless of whether `textValue` exists. Select only the centered text: `textValue` when provided, otherwise the current percentage/unknown value.
- Keep the progress arc driven solely by the existing verified numeric `value`. A null value already yields the neutral background track with no colored progress; do not derive a percentage or needle position from `balance`.
- Extend the focused component test and Playwright coverage to assert the gauge remains visible, balance is centered, the arc stays neutral for null percentage, and existing percentage rendering remains unchanged at desktop and mobile sizes.

## Risks / Trade-offs

- A long balance string could overflow the gauge center → retain centered wrapping text and verify mobile width in Playwright.
