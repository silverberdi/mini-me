# DeepSeek Flash pricing snapshot evidence

- Source: [DeepSeek API Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/)
- Retrieved: `2026-10-16T10:14:19Z`
- Retrieved document SHA-256: `210f102275ccf1a6542f08a3bc9e4b4c7c83278cb74b35217bffa112df6363b2`
- Model: `deepseek-flash`
- Currency: USD
- Conservative input rate: `$0.30 / 1,000,000 tokens` (peak, cache miss)
- Output rate: `$1.20 / 1,000,000 tokens` (peak)
- Budget snapshot identity: `deepseek-flash-peak-20261016-210f102275ccf1a6542f08a3bc9e4b4c7c83278cb74b35217bffa112df6363b2`
- Account binding: account fingerprint derived in-process from the existing configured DeepSeek key; the fingerprint and key are intentionally not recorded here.
- Persistence target: disposable local R01 PostgreSQL database `minime_r01_e2e` only. No authorization or reservation is created by recording pricing.

The dated conservative calculation uses the maximum input and output bounds enforced by the review services; these are cost-estimation inputs, not authorization ceilings:

- Historical CONTRACT REVIEW estimate: `1,000,000 × 0.30 / 1,000,000 + 2,048 × 1.20 / 1,000,000 = $0.3024576`.
- Historical CODE REVIEW estimate: `1,000,000 × 0.30 / 1,000,000 + 4,096 × 1.20 / 1,000,000 = $0.3049152`.
- Historical combined reservation estimate: `$0.6073728`. The pilot ceilings once compared against these estimates are no longer active configuration or current product limits; retain these values solely as dated pricing evidence.

The hash permits an auditor to compare the identified snapshot with the exact retrieved public document artifact. This snapshot is time-bound evidence; later price changes require a fresh official observation before authorization.
