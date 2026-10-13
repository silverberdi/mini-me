---
name: minime-scope-roadmap-guard
description: Keep implementation confined to one vertical-value OpenSpec Change while mandating safe retirement of superseded code within that scope.
---
# Scope and Roadmap Guard — v1
Read `docs/ROADMAP.md`, `docs/BACKLOG.md`, matching `docs/backlog/MM-Rxx.md`, `docs/ENGINEERING_DISCIPLINE.md` and active OpenSpec `proposal/design/specs/tasks`.

- Implement **only** the authorized Change; no future-stage features, unrelated dependencies, speculative abstraction/framework, opportunistic refactor or scope shrinking.
- Do include all backend/UI/DB/provider/skills/tests needed for the **promised vertical value**. A necessary adjacent component is **in scope** when traceable to a SHALL/E2E; if not, stop and request `update`.
- **Mandatory inside same Change**: inventory writers/callers, safely migrate and retire the old behavior that the Change replaces, rerun E2E after deletion. Retirement required by design is **not** an opportunistic refactor. Preserve durable histories/migrations/worktrees.
- Missing E2E, missing retirement evidence, contradictions with Business Intent, or unapproved `RETAIN-WITH-REASON` = BLOCKED with concrete IDs and evidence.

This agent-side skill advises and reports; it is not a claim of a pre-inference executable hook.
