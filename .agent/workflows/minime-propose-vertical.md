---
description: "Prepare the active mini me vertical Change through the installed native OpenSpec propose workflow, reusing a predesigned capability pack"
---

# mini me — OpenSpec propose (vertical Change)

This is a **thin entrypoint to the native OpenSpec propose workflow**. It does not replace `/opsx-propose`, invent a separate schema or authorize `apply`.

1. Confirm the operator selected one MM-Rxx dossier (`docs/backlog/MM-Rxx.md`) and one allowed project/repository. If not, do not invent a Change.
2. Read `docs/ENGINEERING_DISCIPLINE.md`, `docs/CHANGE_DELIVERY_CONTRACT.md`, `docs/agent-capabilities/V1_MANIFEST.md`, `docs/agent-capabilities/RETIREMENT_MAP.md`, `AGENTS.md`, OpenSpec config and selected dossier.
3. Load skills `minime-engineering-discipline`, `minime-real-e2e-proof` and canonical/scope/repo guards. Use an actual installed native OpenSpec propose skill/workflow (`/opsx-propose <slug>` on compatible Antigravity; the correct Codex skill is resolved from `.agents/skills`).
4. Produce proposal/design/**all specs**/tasks, with explicit ID tracing of every Sxx/E0x in the dossier, existing-code census, initial Removal Ledger and 3-level proof plan. No free-form code authoring.
5. Check for drift or duplicate OpenSpec functionality. Stop and show gaps; resolve by OpenSpec `update` when authorized.
6. **Stop after planning.** The installed native propose skill requires a separate new request/dispatch for apply. Do not auto-apply or consume inference for later stages.
