---
name: minime-canonical-context-guard
description: Enforce mini me original business intent, engineering rules, OpenSpec ownership, guardrails and stage boundaries before propose/apply/verify.
---
# Canonical Context and Architecture Drift Guard — v1
Read `docs/BUSINESS_INTENT.md`, `docs/CANONICAL_DECISIONS.md`, `docs/PRODUCT.md`, `docs/ENGINEERING_DISCIPLINE.md`, `docs/CHANGE_DELIVERY_CONTRACT.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/PENDING_DECISIONS.md` where it exists, `AGENTS.md`, the active OpenSpec artifacts, and applicable MM-Rxx dossier. For MM-R01 read `docs/agent-capabilities/R01_IMPLEMENTATION_STARTER.md`.

At **propose** identify verbatim intent and prohibitions, compare proposed features to existing official OpenSpec skills, and map every backlog Sxx/E0x to a spec/scenario/test. Warn on speculation; block violations. At **apply/verify** compare actual candidate source and tool trace with the approved design and task requirements, not just file existence. Explicit contradiction with intent, repo authority, no-merge, agent-only programming or E2E delivery = **BLOCKED**, with precise source and suggested OpenSpec `update`. Do not invent decisions or downgrade semantics merely to pass.

This is an agent instruction, **not an executed deterministic gate**; only registered and tested runtime hooks/guards can claim enforced behavior. Never self-approve, consume fallback provider budget or reassign workspace.
