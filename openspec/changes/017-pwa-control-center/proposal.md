# Proposal: PWA Control Center

## Why

mini me possesses a fully validated, multi-stage autonomous development orchestrator featuring PostgreSQL durable state, OpenSpec governance, isolated candidate worktrees, deterministic checks runners, complementary reviewer pairing (Codex ↔ Antigravity), independent DeepSeek audit gates, container previews with image-digest authority, an interactive Textual TUI (014), a reusable Operator Control Plane (015), and autonomous queue/work selection (016).

However, operators currently lack a primary, modern, multi-device Progressive Web Application (PWA) Control Center. While the TUI serves terminal sessions, the PWA provides the definitive graphical operator experience with rich visual pipeline steppers, interactive container preview validation, real-time queue prioritization telemetry, touch/responsive device support, and seamless control-plane actions across desktop, tablet, and mobile form factors.

Stage 017 delivers the **complete, responsive, production-ready PWA Control Center** as a unified canonical stage composed of 8 internal slices.

## What Changes

This change delivers:

- **017.1 — PWA App Shell + Overview + Queue Observability**:
  - Progressive Web App shell with modern visual hierarchy, brand header, real-time system health, scheduler mode badge (`RUN`/`DRAIN`/`WAIT`), and auto-refresh controls.
  - KPI overview metrics (active runs, queue depth, READY vs blocked count, attention count).
  - Queue prioritization panel with ranked candidates, base scores, starvation aging bonuses, dependency statuses, and explainable admission refusal reasons.

- **017.2 — Runs + Attention + Pipeline Observability**:
  - Live orchestration runs table with status filtering (`IN_PROGRESS`, `NEEDS_HUMAN`, `FAILED`, `COMPLETED`).
  - Interactive pipeline visualization stepper showing current stage (`WORKTREE_SETUP`, `IMPLEMENTATION`, `CHECKS`, `REVIEW`, `AUDIT`, `PREVIEW`, `PR`, `MERGE_GATE`, `CLOSURE`).
  - Active jobs detail view with executor role, attempt counter, blocker claims, and transition history.
  - Prominent Attention Banner for `NEEDS_HUMAN` gates and blocker escalations.

- **017.3 — Candidates + Checks + Review + Audit**:
  - Candidate authority inspector displaying generation lineage, base SHA, head SHA, and immutable candidate status (`CURRENT`, `FROZEN`, `SUPERSEDED`).
  - Deterministic checks runner results with command outputs, exit codes, and diagnostic classifications.
  - Complementary review inspector showing reviewer role, verdict (`READY_TO_MERGE`, `CHANGES_REQUESTED`), and structured findings.
  - DeepSeek independent audit inspector displaying verdict (`PASS`, `FAIL`), risk rating, and audit reasoning.
  - Clear visual distinction between current and stale evidence bindings.

- **017.4 — Container Preview + Guided UI Validation**:
  - Integrated 013 Container Preview lifecycle widget (`BUILDING`, `PROBING`, `READY`, `FAILED`, `STOPPED`).
  - Live preview URL launch button and container port mappings.
  - Guided validation scenario execution checklist with step-by-step instructions, PASS / FAIL submission, and recorded evidence notes.
  - Strict invalidation and `STALE` badge display upon candidate head/base SHA or image digest mutation.

- **017.5 — Operator Actions & Control Plane Integration**:
  - Seamless integration with 015 `ControlPlaneService` APIs (`/api/v1/control-plane/*`).
  - Contextual action buttons dynamically enabled based on server-side action discovery (`continue`, `retry`, `reassign`, `resolve_gate`, `cancel`, `start_preview`, `stop_preview`).
  - Accessible confirmation dialogs with clear impact statements for destructive or mutating operations.
  - Real-time audit log of executed operator actions.

- **017.6 — Orchestration History + GitHub + Provider Observability**:
  - Historical runs and closed change archives with search and timeline playback.
  - GitHub synchronization status (Issue #, Project item, PR #, remote state).
  - Provider capacity & health monitor (`codex`, `antigravity`, `deepseek`, `openrouter`) displaying availability status, latency, and budget consumption.

- **017.7 — Responsive Viewport Optimization + UX Polish**:
  - Tailored layout breakpoints for Desktop Standard (~1366x768), Large (~1920x1080), Ultrawide (~2560x1440), Tablet (~1024x768), and Mobile (~390x844).
  - Effective widescreen utilization eliminating dead zones; high-density tabular and split views; collapsible sidebars and drawers for touch screens.
  - Strict WCAG 2.1 AA accessibility (keyboard navigation, visible focus indicators, semantic ARIA roles, color-independent status badges).

- **017.8 — PWA Web App Manifest + Service Worker + Final Acceptance**:
  - Standard W3C Web App Manifest (`manifest.webmanifest`) supporting standalone app installation on desktop and mobile.
  - High-performance Service Worker (`sw.js`) implementing cache-first / stale-while-revalidate for static shell assets.
  - Graceful degraded / offline indicators when backend connectivity is lost.
  - Zero-defect cross-browser verification and regression test suite.

## Capabilities

### New Capabilities
- `pwa-app-shell-and-queue`: PWA application shell, brand navigation, system health telemetry, KPI summary grid, and autonomous queue prioritization observability.
- `pwa-runs-and-pipeline-observability`: Real-time run list, phase stepper visualization, active job execution details, and attention banner for human gates.
- `pwa-preview-and-operator-actions`: Container preview lifecycle management, guided UI validation runner, and contextual control plane action execution.
- `pwa-responsive-and-offline-pwa`: Web App Manifest installability, Service Worker caching, responsive multi-breakpoint layout, and offline shell resilience.

## Non-Goals (Scope Boundaries)

- Direct client-to-database communication (all requests flow through FastAPI backend services).
- Duplicate client-side orchestration or action eligibility logic (server is single authority).
- Client-side offline mutation queuing (offline behavior is read-only / degraded shell).
- Automated git merge execution without human authorization gate.
- Future roadmap stage 018 end-to-end metrics consolidation (deferred to 018).
