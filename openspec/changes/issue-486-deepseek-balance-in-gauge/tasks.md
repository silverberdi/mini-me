## 1. Preserve the shared gauge

- [x] 1.1 Keep the existing gauge SVG and card structure rendered when a monetary `textValue` is supplied; place the balance in the center and leave the arc neutral when percentage is unavailable.

## 2. Verify balance and percentage presentation

- [x] 2.1 Extend the focused unit and Playwright tests to verify the balance stays inside the shared gauge, the arc is neutral without a verified percentage, and percentage-based gauges remain unchanged.
- [x] 2.2 Run the focused frontend unit test, Dashboard capacity Playwright test at desktop and mobile sizes, and production build; inspect the rendered gauge.
