# Proposal: 021 Work Intake, Project Onboarding, and Backlog Execution

## Problem Statement
Currently, mini me relies on direct human prompts to Antigravity to define, analyze, prepare, and advance work changes. To operate as a true self-hosted autonomous engineering assistant, the system requires a native, product-facing work intake layer. The operator must interact via the PWA backlog rather than sending low-level execution instructions to AI providers.

## Proposed Change
Build the end-to-end work intake layer enabling an authorized operator in the PWA to:
1. Register/bind a project/repository with automated context discovery.
2. Inspect discovered project context (facts, inferred structure, missing context).
3. View and manage a normalized backlog (derived from ROADMAP.md, backlog files, GitHub Issues, or direct intake).
4. Prioritize and prepare work items autonomously into canonical execution artifacts (GitHub Issue, Project item, OpenSpec change).
5. Resolve product ambiguity via inline human questions (`NEEDS_HUMAN` state) without free-form prompt engineering.
6. Verify the Definition of Ready (DoR) and admit the change into the autonomous scheduler to execute through the full SDLC pipeline without manual Antigravity intervention.

## Non-Goals
- Multi-tenant commercial fleet management.
- Natural language chat agent interfaces for generic conversation.
- Autonomous speculative product ideation outside human product boundaries.
- Ollama or new local LLM provider integrations.
- Provider routing policy modifications.

## Capabilities
- `project-onboarding`: External project registration, auto-discovery of configuration/context, conflict detection, and fail-closed binding validation.
- `context-discovery`: Structured discovery of README, docs, ROADMAP.md, BACKLOG.md, and specs into facts, inferred structure, and missing context.
- `backlog-management`: Normalized backlog item model with lifecycle states (`BACKLOG`, `CONTEXT_CHECK`, `PREPARING`, `NEEDS_HUMAN`, `READY`, `ADMITTED`, `RUNNING`, `COMPLETED`, `BLOCKED`).
- `canonical-artifact-generation`: Deterministic OpenSpec generation, GitHub Issue synchronization, and Project v2 item binding.
- `readiness-and-admission`: Automated Definition of Ready evaluation and scheduler admission with duplicate execution suppression.
- `pwa-intake-experience`: Responsive desktop/tablet/mobile PWA interface for projects, backlog, DoR checklist, and question answering.
