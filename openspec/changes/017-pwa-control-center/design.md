# Design: PWA Control Center

## Architecture Overview

The PWA Control Center is the primary operator web interface for `mini me`. It operates strictly as a presentation and interaction client over canonical backend services (`ControlPlaneService`, `DashboardService`, `ContainerPreviewService`, `WorkDiscoveryService`, `SchedulerService`, `ReadinessService`).

```
┌─────────────────────────────────────────────────────────────┐
│                   PWA Control Center                        │
│   (Vanilla ES Modules, CSS Custom Tokens, Service Worker)   │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTPS / JSON REST API
┌──────────────────────────────▼──────────────────────────────┐
│                    FastAPI Backend Router                   │
│   /api/v1/dashboard | /api/v1/control-plane | /api/v1/queue │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                 Canonical mini me Services                  │
│  (Scheduler, ControlPlane, Preview, Checks, Review, Audit)  │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│        PostgreSQL 17 | Git Worktrees | CLI / Providers       │
└─────────────────────────────────────────────────────────────┘
```

## Architectural Decisions

### 1. Technology Stack & Component Structure
- **Framework Choice**: Native Modern Web Architecture (Vanilla ES Modules + CSS Custom Property Design Tokens).
- **Rationale**:
  - Eliminates brittle frontend bundler build chains, transpilation latency, and heavy node_modules runtime footprints in daemon containers.
  - Native ES modules (`<script type="module">`) provide clean encapsulation, dependency imports, and maintainable component separation.
  - Directly served by FastAPI static mount (`/static`) with zero build step required.
- **Directory Layout**:
  ```
  src/minime/static/
  ├── manifest.webmanifest
  ├── sw.js
  ├── index.html
  ├── css/
  │   ├── tokens.css
  │   ├── layout.css
  │   ├── components.css
  │   └── pwa.css
  ├── js/
  │   ├── app.js
  │   ├── state/
  │   │   └── store.js
  │   ├── services/
  │   │   ├── api_client.js
  │   │   └── control_plane_client.js
  │   ├── components/
  │   │   ├── header.js
  │   │   ├── kpi_grid.js
  │   │   ├── attention_banner.js
  │   │   ├── queue_table.js
  │   │   ├── runs_table.js
  │   │   ├── pipeline_stepper.js
  │   │   ├── candidate_inspector.js
  │   │   ├── preview_panel.js
  │   │   ├── action_dialog.js
  │   │   ├── provider_grid.js
  │   │   └── toast.js
  │   └── views/
  │       ├── overview_view.js
  │       ├── runs_view.js
  │       ├── queue_view.js
  │       ├── preview_view.js
  │       ├── history_view.js
  │       └── settings_view.js
  └── icons/
      ├── icon-192.png
      └── icon-512.png
  ```

### 2. Presentation-Only Boundary
- The PWA never contains business logic, database queries, or provider execution logic.
- All mutating operations execute through `POST /api/v1/control-plane/actions/execute`, which enforces optimistic concurrency, idempotency, role permissions, and safety policies.
- Action eligibility is discovered dynamically via `GET /api/v1/control-plane/actions/available?run_id=...` rather than calculated on the client.

### 3. State Management & Real-Time Telemetry
- **Store Architecture**: Centralized, lightweight `AppState` event emitter pattern.
- **Data Fetching**:
  - Periodic polling (configurable: 5s, 10s, 30s, or paused) fetching consolidated telemetry from `/api/v1/dashboard/overview`, `/api/v1/queue/candidates`, and `/api/v1/control-plane/history`.
  - Visibility API integration: pauses polling when browser tab is backgrounded to conserve resources; executes immediate refresh upon regaining focus.
  - Manual instant refresh trigger.

### 4. Responsive Layout & Viewport Systems
- **Fluid Multi-Pane Layout**:
  - **Ultrawide & Large Desktop (>=1920px)**: 3-column split view (Left: Navigation & Queue; Center: Active Run & Pipeline Stepper; Right: Candidate & Preview Inspector). Zero dead space.
  - **Standard Desktop (1200px - 1919px)**: 2-column master-detail view with collapsible side drawer.
  - **Tablet (768px - 1199px)**: Stacked responsive layout with tabbed navigation and bottom action sheet.
  - **Mobile (<768px)**: Single-column optimized view with sticky header, bottom navigation bar, and modal drawers for deep inspections.

### 5. Semantic Design Language & Tokens
- **Theme Support**: Dark (primary) and Light themes with high-contrast WCAG 2.1 AA compliant color ratios.
- **Semantic Colors**:
  - Success (`--color-success`): READY, PASSED, APPROVED, COMPLETED.
  - Attention / Warning (`--color-warning`): NEEDS_HUMAN, STALE, BLOCKED.
  - Failure / Rejection (`--color-danger`): FAILED, REJECTED, CANCELLED.
  - Running / Active (`--color-info`): IMPLEMENTING, CHECKING, REVIEWING, PROBING.
  - Waiting (`--color-muted`): DRAIN, WAIT, QUEUED.
- Visual elements combine color, text labels, and icons to avoid color-only communication.

### 6. PWA Web App Manifest & Service Worker Strategy
- **Web App Manifest (`manifest.webmanifest`)**:
  - `name`: "mini me Control Center"
  - `short_name`: "mini me"
  - `display`: "standalone"
  - `background_color`: "#0f172a"
  - `theme_color`: "#1e293b"
  - `start_url`: "/"
- **Service Worker (`sw.js`)**:
  - Cache static shell assets (`/`, `/static/css/*`, `/static/js/*`, `/static/manifest.webmanifest`) using a stale-while-revalidate strategy.
  - API requests (`/api/*`) are strictly network-first. If network fails, return cached fallback or structured offline status response.
  - Disconnected Banner: When the backend is unreachable, the PWA renders a prominent degraded-mode indicator with automatic retry countdown.

### 7. Security & Secret Redaction
- All diagnostics, logs, check outputs, and environment summaries are sanitized via `minime.logging.redact_secrets` before leaving the server.
- The PWA enforces client-side HTML sanitization when rendering log snippets or error messages to prevent XSS.

### 8. Guided UI Validation & Candidate Authority
- Preview panels display exact candidate metadata: `Head SHA`, `Base SHA`, `Image Digest`, and `Generation`.
- Validation scenarios render interactive checklists. Submitting PASS/FAIL calls `/api/v1/preview/{run_id}/validate`.
- When a candidate SHA changes, prior validation is flagged as `STALE (Invalidated by newer candidate)`.
