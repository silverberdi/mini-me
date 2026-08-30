# Tasks: TUI Operator Console

## Task List

- [x] 1. Canonical Context & OpenSpec Specification
  - [x] 1.1 Persist canonical target operating model in `docs/CANONICAL_DECISIONS.md`.
  - [x] 1.2 Update `docs/ROADMAP.md` marking 013 delivered and 014 active.
  - [x] 1.3 Author OpenSpec specification and validate with `openspec validate --all --strict`.


- [x] 2. TUI Package Foundation & Read-Model Query Client
  - [x] 2.1 Add `textual>=0.70.0` to `pyproject.toml` and reinstall editable package.
  - [x] 2.2 Implement `TuiQueryClient` in `src/minime/tui/client.py` wrapping `OperationsDashboardService` with async non-blocking queries and secret redaction.
  - [x] 2.3 Define TUI state models, reactive data containers, and helper formatters in `src/minime/tui/models.py`.

- [x] 3. Information Architecture, Layout & TCSS Styling
  - [x] 3.1 Author `src/minime/tui/styles.tcss` with responsive layout rules (narrow, normal, wide), panel borders, and semantic color classes.
  - [x] 3.2 Implement `HeaderWidget` with system health, scheduler mode badge, active/attention counters, and keybinding hints.
  - [x] 3.3 Implement `HelpModal` with keyboard shortcut references and navigation guide.

- [x] 4. Core TUI Views & Widgets
  - [x] 4.1 Implement `OverviewView` in `src/minime/tui/views/overview.py` with System Health, Attention Queue, Active Executions, Provider Capacity, and Recent Completions.
  - [x] 4.2 Implement `ChangesView` in `src/minime/tui/views/changes.py` with interactive `DataTable`, status badges, filtering, and selection handlers.
  - [x] 4.3 Implement `RunDetailView` in `src/minime/tui/views/detail.py` with Run Metadata Header, Visual Pipeline Stage Stepper, Candidates Lineage Tree, Checks Results Table, Complementary Review, DeepSeek Audit Risk, and Transition Timeline.
  - [x] 4.4 Implement `PreviewValidationView` in `src/minime/tui/views/preview.py` projecting 013 container preview lifecycle (`BUILDING`, `PROBING`, `READY`, `FAILED`), candidate authority binding, guided validation scenarios checklist, and `STALE` validation warnings.

- [x] 5. Application Shell & CLI Entrypoints
  - [x] 5.1 Implement `MiniMeTuiApp` in `src/minime/tui/app.py` binding views, periodic background refresh, keyboard shortcuts, and error boundary handling.
  - [x] 5.2 Add `minime console` and `minime tui` commands in `src/minime/cli/main.py`.

- [x] 6. Responsive Layout Optimization & Density Tuning
  - [x] 6.1 Optimize wide / ultrawide layout (>170 cols) with 3 balanced columns eliminating unused whitespace.
  - [x] 6.2 Optimize normal layout (110–170 cols) with balanced 2 columns.
  - [x] 6.3 Optimize narrow layout (<110 cols) with vertical stacking and tabbed cards avoiding horizontal clipping.

- [x] 7. Automated TUI Tests & Visual Acceptance
  - [x] 7.1 Unit tests for `TuiQueryClient`, formatters, and secret redaction in `tests/tui/`.
  - [x] 7.2 Headless `textual.pilot` tests for all 4 views, keyboard navigation, and tab switching.
  - [x] 7.3 Responsive layout tests verifying narrow (80x24), normal (140x40), and wide (200x50) viewports without broken borders or overlap.
  - [x] 7.4 013 preview and validation state projection tests verifying `BUILDING`, `READY`, scenario steps, `PASS`, and `STALE` candidate invalidation.
  - [x] 7.5 Visual acceptance matrix verification covering 20 required operational states.

- [ ] 8. Canonical Verification, Review, Audit, and Merge
  - [x] 8.1 Run full check suite: pytest, ruff check, git diff --check, openspec validate --all --strict, alembic heads.
  - [ ] 8.2 Candidate freeze and complementary review.
  - [ ] 8.3 DeepSeek Direct independent audit.
  - [ ] 8.4 Autonomous merge and post-merge archive/cleanup.

