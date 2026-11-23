## 1. Shared provider-capacity projection

- [x] 1.1 Replace provider-specific gauge value branches with one shared precedence rule for verified percentage, USD balance fallback, and unknown state; preserve exact monetary text.
- [x] 1.2 Show the USD 20 = 100% visual reference beside the capacity heading and keep all four providers on the same gauge structure.

## 2. Regression evidence

- [x] 2.1 Add focused Playwright coverage for USD 0, USD 10, USD 20+, a provider-reported percentage taking precedence, non-USD balance, and unknown capacity.
- [x] 2.2 Run the focused Playwright coverage at desktop and mobile viewports and verify the OpenRouter percentage remains unchanged.
