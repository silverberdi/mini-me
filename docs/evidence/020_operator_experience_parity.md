# 020 — Operator Experience Parity & Production Console Reliability Evidence

## Milestone Summary
- **Change Name**: `020-operator-experience-parity-and-production-console-reliability`
- **Target Repository**: `silverberdi/mini-me`
- **Canonical Server Runtime**: `192.168.0.194`
- **Public Operator Console**: `https://mini-me.silverman.pro`
- **Sub-deliverables**:
  - `020.1 — PWA Operator Parity`
  - `020.2 — TUI Production Runtime Reliability`

---

## 1. Initial vs Final Capability Matrix

| # | Operational Capability | Initial PWA | Initial TUI | Final PWA | Final TUI | Parity Status |
|---|------------------------|-------------|-------------|-----------|-----------|---------------|
| 1 | Overview & Status | PWA_FULL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 2 | System Health & DB Connectivity | PWA_FULL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 3 | Attention & Blockers | PWA_FULL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 4 | Queue Observability & Priorities | PWA_FULL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 5 | Scheduler Mode (RUN/DRAIN/WAIT) | PWA_FULL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 6 | Provider Health & Capacities | PWA_FULL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 7 | Active Changes Inspection | PWA_FULL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 8 | Active Runs Monitoring | PWA_FULL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 9 | Run Detail & Stage Stepper | PWA_FULL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 10 | Candidate Authority & SHAs | PWA_FULL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 11 | Candidate Lineage & Generations | PWA_FULL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 12 | Deterministic Checks Inspection | PWA_FULL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 13 | Complementary Review Inspection | PWA_FULL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 14 | DeepSeek Audit Inspection | PWA_FULL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 15 | Preview Session Inspection | PWA_FULL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 16 | Guided Validation Scenarios | PWA_FULL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 17 | Historical Audit Trail Tab | MISSING | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 18 | GitHub PR Reconciliation State | PWA_FULL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 19 | Provider Efficiency & Telemetry | MISSING | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 20 | Post-Merge Closure Status | PWA_FULL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 21 | Action: Continue / Resume | PWA_PARTIAL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 22 | Action: Retry Stage (with params) | PWA_PARTIAL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 23 | Action: Reassign Executor (with target)| PWA_PARTIAL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 24 | Action: Resolve Gate (with decision)| PWA_PARTIAL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 25 | Action: Cancel Run (with confirm) | PWA_PARTIAL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 26 | Action: Start Preview | PWA_FULL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 27 | Action: Teardown Preview | PWA_FULL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 28 | Action: Recover Locks (with confirm)| PWA_PARTIAL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 29 | Action: Reconcile Post-Merge (confirm)| PWA_PARTIAL | TUI_FULL | PWA_FULL | TUI_FULL | 100% PARITY |
| 30 | Production Interactive Shell Launch | N/A | MISSING (FAIL) | N/A | TUI_FULL | 100% RELIABILITY |

---

## 2. Root Cause Analysis & Resolution of TUI Defect (020.2)

### Root Cause
When launching the interactive CLI or TUI (`minime console`, `minime status`) over an interactive SSH session as user `silverman`, systemd's `EnvironmentFile=/etc/minime/minime.env` was not present in the user's interactive shell environment. Consequently, `MINIME_DATABASE_URL` was unset, throwing:
`Database URL is not configured. Please set MINIME_DATABASE_URL`

### Secure Resolution
1. **Canonical Config Discovery**: Enhanced `src/minime/config.py` with `discover_and_load_env_file()` which searches:
   - Explicit `MINIME_CONFIG_PATH` or `MINIME_ENV_FILE`
   - Canonical system configuration `/etc/minime/minime.env`
   - Workspace `.env`
2. **Secure POSIX Group Membership**:
   - `/etc/minime/minime.env` configured as `0640 root:minime`.
   - Authorized operators added to Linux group `minime`.
   - File is NOT world-readable, preventing arbitrary local user inspection.
3. **Canonical Launchers**:
   - `/usr/local/bin/minime`: Production CLI launcher.
   - `/usr/local/bin/minime-console`: Direct console launcher.
4. **Zero Secret Exposure**:
   - 0 plaintext credentials written to shell history or `.bashrc`.
   - 0 manual `export MINIME_DATABASE_URL=...` commands required.
   - Secrets remain securely isolated to `/etc/minime/minime.env`.

---

## 3. PWA Operator Parity Implementation (020.1)

### Shared Control Plane & Discovery
- PWA dynamically discovers available actions from `/api/v1/control-plane/actions/available?project_id=...&change_name=...` and renders them with semantic labels, disabled tooltips, and appropriate styling.
- Backend owns 100% of action eligibility, validation, authorization, and concurrency protection.

### Parameter Modals & Safety Confirmations
- **`<dialog id="actionParamDialog">`**: Handles parameterized actions:
  - `REASSIGN`: Select target executor (`codex` / `antigravity`).
  - `RESOLVE_GATE`: Select decision (`PROCEED` / `REWORK` / `ABORT`) and input operator notes.
  - `RETRY`: Select stage and input retry reason.
- **`<dialog id="actionDialog">`**: Handles high-impact/destructive actions:
  - `CANCEL`, `RECOVER_LOCKS`, `RECONCILE_POST_MERGE`.
  - Displays explicit warning, target change/run ID, expected impact, and requires explicit confirmation.

### Telemetry & Audit Surfaces
- **Efficiency & Telemetry Tab (`#efficiencyTab`)**: Displays Productive Attempt Ratio, Primary Implementer, Reviewer Independence (PASS), Self-Hosting Native %, Same-SHA Retries/Suppressed, Candidate Generations, and Reassignments.
- **Action History Tab (`#actionHistoryTab`)**: Displays chronological operator control actions, status (`EXECUTED`, `FAILED`, `CANCELLED`), timestamps, and operator audit records.

---

## 4. Responsive Viewport & Browser Verification

Executed automated headless Chrome DevTools Protocol test suite (`tests/test_pwa_real_browser.py`) on server `192.168.0.194`:
- **Unauthenticated login redirect**: PASSED (Auth shell hides telemetry).
- **Desktop Standard (1366x768)**: PASSED (0 horizontal overflow, 4 KPI cards, split layout).
- **Ultrawide (2560x1440)**: PASSED (Full width utilization > 2000px, 3-column split).
- **Tablet Landscape (~1024x768)**: PASSED (0 overflow, panels fit within bounds).
- **Mobile (~390x844)**: PASSED (Sticky top navigation, bottom navigation bar, >= 40px touch targets).
- **PWA Manifest & Service Worker**: PASSED (`manifest.webmanifest` standalone, SW registered).
- **Interactive Modals & Theme**: PASSED (Theme toggle, dialog `.showModal()`, parameter modal cancel/submit).
- **020 Efficiency & Action History Tabs**: PASSED (Active pane switching and rendering).

---

## 5. Automated Verification Results
- **Pytest Suite**: 595 passed, 10 skipped, 0 failed in 57.30s.
- **Ruff Linter**: 0 errors across 524 files.
- **Ruff Formatter**: 0 errors across 524 files.
- **ChecksRunner**: Sequential deterministic checks (`ruff-check`, `ruff-format`, `pytest`) PASSED.
- **Public Operator Endpoint**: `https://mini-me.silverman.pro` HTTP/2 200 OK via Cloudflare Tunnel.
- **Server Workloads**: All 14 Docker containers and 4 Cloudflare ingress routes healthy.
