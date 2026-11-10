## 1. Recovery checkpoint behavior

- [x] 1.1 Bind the strictly validated native Update's explicit task disposition changes to the same candidate identity in the existing durable checkpoint.
- [x] 1.2 Reconcile only validated changed task dispositions during Apply regression comparison; preserve all unrelated regression checks and idempotency.

## 2. Evidence and verification

- [x] 2.1 Add focused tests for an authorized reclassification that no longer falsely trips regression and for an unrelated task regression that still fails closed.
- [x] 2.2 Extend PostgreSQL-backed E2E coverage for accepted operator response, native Update validation, and same-candidate Apply recovery; run OpenSpec Verify and record evidence.
