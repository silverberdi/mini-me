# Proposal: TUI Operator Console

## Why

mini me autonomously executes software-delivery cycles and provides real-time visibility through an operations dashboard. However, operating, navigating, and troubleshooting mini me still relies heavily on browser interfaces and ad-hoc CLI commands.

014 introduces the first interactive terminal operator console (`minime console` / `minime tui`), providing operators with a powerful, responsive, keyboard-driven terminal experience. Operators can immediately understand system health, active executions, attention-demanding blockers, candidate lineages, deterministic checks diagnostics, complementary review verdicts, DeepSeek audit risks, 013 preview and validation states, and execution histories without querying PostgreSQL directly, reconstructing logs, or manually inspecting worktrees.

## What Changes

This change delivers:

- **TUI Framework & Application Core (`src/minime/tui/`)**:
  - Built with Python-native Textual framework (`textual>=0.70.0`), featuring async event loops, reactive properties, and robust terminal rendering.
  - `MiniMeTuiApp`: Main console application shell with periodic background refresh, status headers, tabbed view navigation, and modal dialogues.
- **Read-Model Query Boundary (`src/minime/tui/client.py`)**:
  - Decoupled query client consuming canonical `OperationsDashboardService` and domain services.
  - Zero direct PostgreSQL querying from widgets; strict isolation between persistence layer and presentation layer.
  - Comprehensive secret redaction ensuring credentials, API keys, and tokens are never rendered in terminal widgets.
- **Information Architecture & Multi-View Navigation**:
  - **Overview View**: System status, scheduler mode, active executions, attention queue, provider capacity, and recent completions.
  - **Changes & Runs View**: Interactive data table of all discovered and active changes with status filtering and real-time stage tracking.
  - **Run Detail & Pipeline View**: Visual pipeline stage progression stepper, candidate lineage hierarchy (current authority vs historical/superseded), check results, complementary review findings, DeepSeek audit risk, and transition timeline.
  - **Preview & Validation View (013 Integration)**: Real-time projection of container preview lifecycle (`BUILDING`, `PROBING`, `READY`, `FAILED`), endpoint URLs, image digests, guided validation scenario steps, PASS/FAIL verdicts, and prominent `STALE` candidate invalidation alerts.
  - **Attention Queue Modal / Panel**: Immediate drill-down into `NEEDS_HUMAN`, `WAITING`, and failed stage blockers with remediation guidance.
- **Responsive Layout & Visual Hierarchy (`src/minime/tui/styles.tcss`)**:
  - Dynamic adaptation across terminal width classes:
    - **Narrow (<110 cols)**: Stacked cards, compact summaries, and collapsible detail views.
    - **Normal (110–170 cols)**: Balanced two-column layout with change lists on the left and active pipeline details on the right.
    - **Wide / Ultrawide (>170 cols)**: Three-column layout maximizing terminal width without empty dead zones or oversized margins.
  - Semantic color palette (Green/Success, Yellow/Attention/Stale, Red/Failure, Cyan/Running, Dim/Neutral), clear box borders, badges, and progress indicators.
- **Keyboard-First Interaction**:
  - Intuitive keybindings: `q` (quit), `r` (refresh), `1`-`4` / `Tab` (view tabs), `j`/`k`/Arrows (navigation), `Enter` (drill-down), `Esc` (back), `?`/`F1` (help modal).
- **CLI Entrypoints (`src/minime/cli/main.py`)**:
  - Added `minime console` and `minime tui` commands.
- **Comprehensive Automated & Responsive Testing**:
  - Headless TUI pilot tests verifying navigation, layout responsiveness across terminal sizes, empty/degraded states, secret redaction, and 013 preview/validation projections.

## Capabilities

### New Capabilities
- `tui-operator-console`: Interactive terminal operator console providing real-time multi-project observability, pipeline tracking, candidate lineage, 013 preview projection, and keyboard-first terminal navigation.

### Modified Capabilities
- None (consumes established `execution-operations-dashboard`, `candidate-validation-authority`, and `container-preview-runtime` capabilities).

## Non-Goals (Scope Boundaries)
- Implementing the 015 Operator Actions / Control Plane (no broad mutation semantics, agent reassignment, or arbitrary DB updates).
- Implementing 016 Autonomous Queue & Work Selection.
- Implementing 017 PWA Control Center.
- Hand-built curses UI or frontend web frameworks.

## Impact
- `pyproject.toml`: Added `textual>=0.70.0` dependency.
- `docs/CANONICAL_DECISIONS.md`: Persisted canonical target operating model.
- `docs/ROADMAP.md`: Updated canonical roadmap status.
- `src/minime/tui/`: New package containing app, widgets, screens, client, and TCSS styles.
- `src/minime/cli/main.py`: Added `console` and `tui` CLI commands.
- `tests/tui/`: Unit, integration, responsive layout, and projection tests.
