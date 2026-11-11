## 1. Cancellation contract

- [x] 1.1 Add a focused cancellation service that validates Run/project identity, active nonterminal state, and absence of an active stage job; persist the cancellation audit and terminal transition transactionally.
- [x] 1.2 Reuse the existing durable worktree ownership and cleanup checks after cancellation; surface unresolved cleanup without undoing or misreporting the terminal Run transition.

## 2. Operator entry points

- [x] 2.1 Add the authenticated Run-targeted API endpoint and request model with reason and idempotency key.
- [x] 2.2 Add `minime request cancel` targeting an explicit Run ID; retain `request complete` behavior unchanged.
- [x] 2.3 Add a confirmed cancellation control to the current Run PWA view, shown only for an eligible human gate, with success and failure feedback.

## 3. Evidence

- [x] 3.1 Add focused domain/API/CLI/frontend coverage for success, wrong project, active job, stale/terminal Run, duplicate key, and declined UI confirmation.
- [x] 3.2 Prove against PostgreSQL that one cancellation releases the active Run selector exactly once, preserves previous stop details, records actor/reason, and leaves unrelated Runs and worktree ownership intact when cleanup cannot be proven.
- [x] 3.3 Run focused tests, strict OpenSpec validation, formatting/lint, frontend build, and diff checks; report any pre-existing failures separately.
