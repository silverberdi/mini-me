## 1. Recovery rule

- [x] 1.1 Validate finite AUTH_REQUIRED/no-progress duplicate chains and one exact suppression event per duplicate; preserve the CREATED-only boundary. Evidence: `_has_durable_auth_required_created_recovery()` validates the anchor, every attempt and per-attempt event, and remains gated on CREATED ownership.
- [x] 1.2 Add adversarial cases for missing, extra, mismatched, mistimed, and cross-job suppression evidence and contradictory attempt history. Evidence: PostgreSQL regression module rejects missing/duplicate/wrong-job/wrong-attempt/early suppression, non-AUTH_REQUIRED duplicate, SHA drift, progress, ambiguous attempts, stale/expired claim, candidate, and DELETED ownership.

## 2. Durable regression and validation

- [x] 2.1 Extend isolated PostgreSQL + real Git CONTINUE integration to four exact attempts and two suppressions, reaching only a diagnostic runner. Evidence: the canonical CONTINUE integration creates four durable attempts matching the reported executor/outcome/productivity pattern, two scoped suppression events, and reaches the diagnostic runner on the same CREATED path, branch, snapshot, and ownership identity; no provider inference is invoked.
- [x] 2.2 Run focused and adjacent tests, Ruff, strict OpenSpec validation, and `git diff --check`. Evidence: 56 focused PostgreSQL/Git and adjacent tests pass; Ruff check and format pass; strict change validation and `git diff --check` pass.
