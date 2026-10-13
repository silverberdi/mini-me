---
description: "Validate an OpenSpec Change against engineering rules, actual agent E2E, code retirement and deployed behavior"
---

# mini me — OpenSpec verify (vertical Change)

1. Open the active MM-Rxx dossier and actual OpenSpec `proposal/design/specs/tasks`; read `docs/ENGINEERING_DISCIPLINE.md`, `docs/CHANGE_DELIVERY_CONTRACT.md` and capability contracts.
2. Load skills `minime-real-e2e-proof`, `minime-engineering-discipline`, `minime-safe-retirement`, canonical/scope/repo guards, and applicable project skills.
3. Run **native** `/opsx-verify <slug>` or the installed Codex OpenSpec verify skill. Validate requirements and intended architecture, full Sxx→E0x matrix, task evidence, negatives, UI/browser when applicable and actual provider-workflow trace.
4. Verify removal ledger: all replaced routes and imports/callers migrated, E2E **after deletion**, no duplicated active writers; retain historical data. Exceptions require explicit human approval and are visible as incomplete.
5. Separate `TECHNICAL_PASS`, `E2E_PASS`, and `DEPLOYED_VERIFIED`. Real agent/OpenSpec/GitHub behavior cannot be proven by a fake runner; a health HTTP 200 cannot prove deployed value.
6. Independent reviewer uses exact candidate SHA and reports security, regression, maintainability, architecture drift, tests and code debt **without editing**.
7. Fail closed on missing/contradictory evidence; route corrections via OpenSpec `update/apply/verify` and re-review, not free-form programming prompts. No auto-merge or unapproved quota.
