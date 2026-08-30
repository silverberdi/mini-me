# Design: TUI Operator Console

## Architecture & Technology Choice

### 1. Framework Decision & Rationale

We select **Textual** (`textual>=0.70.0`) as the Python-native TUI framework for mini me.

**Rationale:**
- **Modern Python Native**: Built entirely on top of Python 3.12+ async/await primitives and `rich`, integrating seamlessly with our existing stack.
- **Robust Layout Engine**: Features a CSS-like layout engine (TCSS) supporting grid, horizontal, and vertical containers, percentage and fractional sizing, responsive media queries, and clean box styling.
- **Reactive State & Event Driven**: Built-in reactive properties (`reactive()`) and message bus ensure clean decoupling between state updates and UI rendering.
- **Headless Testing (Textual Pilot)**: Textual includes a built-in testing harness (`App.run_test()`) allowing deterministic, automated headless testing of key presses, clicks, widget states, and terminal resizing without spawning physical pseudo-terminals.
- **Superiority over alternatives**:
  - Raw `curses`: Brittle, requires manual coordinate math, lacks built-in async support, lacks rich styling/widgets, and is notoriously difficult to test deterministically.
  - `prompt_toolkit`: Excellent for CLI prompts/REPLs, but complex and less ergonomic for full-screen multi-pane responsive dashboards.
  - `blessed`/`asciimatics`: Slower release velocity, less standard layout engine, and smaller ecosystem compared to Textual.

### 2. Boundary Architecture & Decoupling

```text
+-------------------------------------------------------------+
|                      Textual TUI Layer                      |
| (MiniMeTuiApp, OverviewScreen, RunDetailScreen, Widgets)    |
+-------------------------------------------------------------+
                              |
                              | Async Query Client
                              v
+-------------------------------------------------------------+
|                     TuiQueryService                         |
| (Consumes OperationsDashboardService & Domain DTOs)         |
+-------------------------------------------------------------+
                              |
                              | Unit of Work / Repositories
                              v
+-------------------------------------------------------------+
|                  PostgreSQL Database Layer                  |
| (Durable state: Projects, Runs, Jobs, Validations, Events)  |
+-------------------------------------------------------------+
```

**Non-Negotiable Rules:**
1. **Zero Direct DB Access from Widgets**: TUI widgets never import SQLAlchemy models or execute direct SQL queries. All data access goes through `TuiQueryService` wrapping `OperationsDashboardService`.
2. **Strict Secret Redaction**: All string fields and diagnostic snippets pass through `minime.logging.redact_secrets` before reaching display widgets.
3. **Async Non-Blocking Data Fetching**: Background data refresh runs asynchronously without blocking the UI thread or causing sluggish keypress responses.

---

## Information Architecture & Screen Design

### 1. Header & System Bar
- Displays product identity (`mini me console`), database connectivity status, scheduler mode badge (`RUN`, `DRAIN`, `WAIT`), active runs counter, attention items counter, and quick keybinding hints.

### 2. Main Views (Tabbed Navigation)

#### View 1: Overview (`overview`)
- **System Health Card**: Database status, GitHub App identity, scheduler mode, queue depth.
- **Attention Queue Panel**: Real-time list of all runs requiring human intervention (`NEEDS_HUMAN`), waiting for capacity (`WAITING`), or blocked in recovery, with canonical stop codes and remediation hints.
- **Active Executions Panel**: Runs currently executing with executor name, current stage, candidate SHA, and elapsed time.
- **Recent Completions Panel**: Recently finished runs with merge status, PR links, and audit outcomes.
- **Provider Capacity & Health**: Real-time status of configured CLI and API providers.

#### View 2: Changes & Runs (`changes`)
- Interactive `DataTable` listing all known changes across registered projects.
- Columns: `Project`, `Change Name`, `Status`, `Stage`, `Executor`, `Gen`, `Candidate SHA`, `PR #`, `Updated`.
- Row selection immediately switches to the detailed Run View for that change.

#### View 3: Run Detail & Pipeline (`detail`)
- **Run Metadata Header**: Full project/change identifiers, run ID, active job ID, current stage, generation, candidate SHA, base SHA, and target branch.
- **Pipeline Stage Stepper**: Visual progression across the 6 core phases:
  `[1. Readiness] -> [2. Implementation] -> [3. Checks] -> [4. Review] -> [5. DeepSeek Audit] -> [6. PR & Merge]`
  Each phase rendered with color-coded status badges (`PASSED`, `RUNNING`, `FAILED`, `BLOCKED`, `WAITING`, `NOT_STARTED`).
- **Candidate Lineage Hierarchy**: Lineage tree distinguishing current authoritative candidate from historical/superseded candidates with generation numbers, commit SHAs, and manifest hashes.
- **Deterministic Checks Panel**: Results table showing check name, status (`PASS`/`FAIL`), execution duration in milliseconds, exit code, and redacted diagnostic output snippet.
- **Review & Audit Authority**:
  - Complementary review verdict (`READY_TO_MERGE`, `CHANGES_REQUIRED`), reviewer model, mixed-authorship indicator, material findings count, and stale-candidate warnings.
  - DeepSeek audit status (`PASS`, `BLOCKED`), risk level (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`), and material findings.
- **Timeline / Event History**: Chronological stream of state transitions and events.

#### View 4: Preview & Guided Validation (`preview` — 013 Integration)
- Dedicated view exercising 013 container preview and guided validation capabilities:
  - **Preview Session State**: Status (`BUILDING`, `STARTING`, `PROBING`, `READY`, `FAILED`), allocated port, container name, preview URL, and image digest (`sha256:...`).
  - **Candidate Authority Binding**: Tuple `(head_sha, base_sha, image_digest)` matching current candidate.
  - **Guided Validation Scenarios**: Interactive list of validation scenarios with ordered steps, descriptions, viewports, and expected outcomes.
  - **Validation Authority Status**: Latest operator verdict (`PASS`/`FAIL`), timestamp, operator identity, and explicit `STALE VALIDATION` alerts whenever candidate identity has changed.

---

## Responsive Layout System & Viewport Adaptation

The TUI adapts dynamically to terminal dimensions using CSS Grid and Flexbox layouts:

```text
+-----------------------------------------------------------------------------------------------+
| WIDE / ULTRAWIDE LAYOUT (>170 cols)                                                           |
| +-------------------------+-----------------------------------+-----------------------------+ |
| | Col 1: System & Nav     | Col 2: Active Pipeline & Stepper  | Col 3: Candidate & Evidence | |
| | - System Health Card    | - Run Metadata & Status           | - Candidate Authority (Gen) | |
| | - Attention Queue       | - 6-Phase Pipeline Stepper        | - Checks Results Summary    | |
| | - Changes / Runs Table  | - Active Stage Details            | - Review & Audit Authority  | |
| | - Provider Capacity     | - Transition Timeline History     | - Preview & Validation (013)| |
| +-------------------------+-----------------------------------+-----------------------------+ |
+-----------------------------------------------------------------------------------------------+

+-----------------------------------------------------------------------------------------------+
| NORMAL LAYOUT (110 - 170 cols)                                                                |
| +--------------------------------------+----------------------------------------------------+ |
| | Left Column (40% width)              | Right Column (60% width)                           | |
| | - Attention Queue & Changes List     | - Run Detail, Pipeline Stepper, Evidence Tabs       | |
| | - Provider & System Health           |   (Checks, Review, Audit, Preview & Validation)    | |
| +--------------------------------------+----------------------------------------------------+ |
+-----------------------------------------------------------------------------------------------+

+-----------------------------------------------------------------------------------------------+
| NARROW LAYOUT (<110 cols)                                                                     |
| +-------------------------------------------------------------------------------------------+ |
| | Full-width single column with Tabbed Navigation & Compact Cards                           | |
| | [ Overview Tab ]  [ Changes Tab ]  [ Run Detail Tab ]  [ Preview Tab ]                    | |
| +-------------------------------------------------------------------------------------------+ |
+-----------------------------------------------------------------------------------------------+
```

**Responsive Design Principles:**
- **No Wasted Width**: In wide terminals, data expands horizontally into 3 columns instead of centering narrow boxes with massive blank margins.
- **Density without Chaos**: Information grouped cleanly using panel borders, subtle background tints, and progressive disclosure (drill-down instead of infinite unformatted text).
- **Graceful Narrow Degradation**: On narrow terminals, multi-column layouts stack vertically and switch to tabs, preserving readability without horizontal truncation.

---

## Visual Hierarchy & Semantic Styling

### Color Palette (Terminal TrueColor / ANSI)
- **Success / Green** (`#4ade80`): Passed checks, approved review, healthy status, low audit risk.
- **Attention / Yellow** (`#facc15`): `NEEDS_HUMAN`, `WAITING_CAPACITY`, stale validation, medium audit risk.
- **Failure / Red** (`#f87171`): Failed checks, rejected review, high/critical audit risk, blocked recovery.
- **Running / Cyan** (`#38bdf8`): Active jobs, building previews, probing health endpoints.
- **Neutral / Dim** (`#9ca3af`): Superseded candidates, skipped checks, historical items.

### Typography & Formatting
- Section titles styled with bold weight and semantic accent borders (`round` and `solid`).
- Badges and status pills enclosed in brackets (`[READY]`, `[RUNNING]`, `[PASS]`).
- Commit SHAs and image digests formatted as 8-character short forms with full hex displayed in detail modals.

---

## Keyboard Navigation

| Key | Action |
|---|---|
| `q` / `Ctrl+C` | Quit console |
| `r` | Refresh operational data immediately |
| `1` | Switch to Overview tab |
| `2` | Switch to Changes tab |
| `3` | Switch to Run Detail tab |
| `4` | Switch to Preview & Validation tab |
| `j` / `Down` | Navigate down in lists/tables |
| `k` / `Up` | Navigate up in lists/tables |
| `Enter` | Select change / drill down into detail |
| `Esc` | Return to Overview / Dismiss modal |
| `?` / `F1` | Show keyboard shortcuts help modal |

---

## Error Handling & Security

- **Database Disconnection / Degraded Mode**: When database or daemon is temporarily unreachable, TUI displays a clear warning card with reconnect attempts instead of crashing with Python stack traces.
- **Secret Sanitization**: All strings displayed in widgets are filtered through `redact_secrets()`, ensuring environment variables, API tokens, and credentials are never exposed in terminal screens or log files.
