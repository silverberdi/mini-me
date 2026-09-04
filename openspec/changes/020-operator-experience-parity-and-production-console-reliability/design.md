# Design: 020 — Operator Experience Parity & Production Console Reliability

## Architecture

```text
                  Canonical Backend / Control Plane
                 /                                 \
      OperationsDashboardService             ControlPlaneService
                 |                                   |
         FastAPI REST & SSE               PostgreSQL Persistence
                 |                                   |
              PWA UI                             TUI Console
     (Desktop / Tablet / Mobile)             (SSH Terminal Fallback)
```

## 1. Capability Matrix (PWA vs TUI)

| Capability / Surface | PWA Current | TUI Current | Target 020 State | Target Parity |
|---|---|---|---|---|
| 1. Overview & KPIs | `PWA_FULL` | `TUI_FULL` | `FULL` | 100% |
| 2. System Health & DB | `PWA_FULL` | `TUI_FULL` | `FULL` | 100% |
| 3. Attention & Blockers | `PWA_FULL` | `TUI_FULL` | `FULL` | 100% |
| 4. Autonomous Queue | `PWA_FULL` | `TUI_FULL` | `FULL` | 100% |
| 5. Scheduler Status | `PWA_FULL` | `TUI_FULL` | `FULL` | 100% |
| 6. Provider Health/Capacity | `PWA_FULL` | `TUI_FULL` | `FULL` | 100% |
| 7. Changes Table & Filter | `PWA_FULL` | `TUI_FULL` | `FULL` | 100% |
| 8. Runs & In-Flight Status | `PWA_FULL` | `TUI_FULL` | `FULL` | 100% |
| 9. Run Detail & Header | `PWA_FULL` | `TUI_FULL` | `FULL` | 100% |
| 10. Candidate Authority | `PWA_FULL` | `TUI_FULL` | `FULL` | 100% |
| 11. Candidate Lineage/Gen | `PWA_FULL` | `TUI_FULL` | `FULL` | 100% |
| 12. Deterministic Checks | `PWA_FULL` | `TUI_FULL` | `FULL` | 100% |
| 13. Complementary Review | `PWA_FULL` | `TUI_FULL` | `FULL` | 100% |
| 14. DeepSeek Direct Audit | `PWA_FULL` | `TUI_FULL` | `FULL` | 100% |
| 15. Container Preview | `PWA_FULL` | `TUI_FULL` | `FULL` | 100% |
| 16. Guided UI Validation | `PWA_FULL` | `TUI_FULL` | `FULL` | 100% |
| 17. Lifecycle Timeline | `PWA_FULL` | `TUI_FULL` | `FULL` | 100% |
| 18. GitHub Issue / PR | `PWA_FULL` | `TUI_FULL` | `FULL` | 100% |
| 19. Provider Efficiency | `PWA_PARTIAL` | `TUI_FULL` | `FULL` (New dedicated tab & KPI) | 100% |
| 20. Post-Merge Reconciliation | `PWA_FULL` | `TUI_FULL` | `FULL` | 100% |
| 21. Action: Continue / Resume | `PWA_PARTIAL` | `TUI_FULL` | `FULL` (Payload fix + concurrency) | 100% |
| 22. Action: Retry Stage | `PWA_PARTIAL` | `TUI_FULL` | `FULL` (Stage selector modal) | 100% |
| 23. Action: Reassign Executor | `PWA_PARTIAL` | `TUI_FULL` | `FULL` (Executor selector modal) | 100% |
| 24. Action: Resolve Gate | `PWA_PARTIAL` | `TUI_FULL` | `FULL` (Decision & notes modal) | 100% |
| 25. Action: Cancel Run | `PWA_PARTIAL` | `TUI_FULL` | `FULL` (Danger confirmation modal) | 100% |
| 26. Action: Start Preview | `PWA_FULL` | `TUI_FULL` | `FULL` | 100% |
| 27. Action: Teardown Preview | `PWA_FULL` | `TUI_FULL` | `FULL` | 100% |
| 28. Action: Recover Locks | `PWA_PARTIAL` | `TUI_FULL` | `FULL` (Exposed in action toolbar) | 100% |
| 29. Action: Reconcile Post-Merge | `PWA_PARTIAL` | `TUI_FULL` | `FULL` (Exposed in action toolbar) | 100% |
| 30. Action History Audit Trail | `PWA_PARTIAL` | `TUI_FULL` | `FULL` (New dedicated tab) | 100% |

## 2. PWA Action Discovery & Safety Architecture
- Action discovery via `GET /api/v1/control-plane/actions/available?run_id={run_id}`.
- Payload mapping: Pass `project_id`, `change_name`, `run_id`, `action_type`, `expected_stage`, `expected_generation`, `expected_candidate_sha`, `parameters`.
- Parameter dialogs rendered dynamically using native `<dialog>` element.
- Destructive / high-impact actions (`CANCEL`, `RECOVER_LOCKS`, `RECONCILE_POST_MERGE`, `RETRY`) present explicit confirmation modals showing target change, impact description, and state invariants.

## 3. TUI Production Runtime Configuration
- Root cause: Missing environment loading when running interactively over SSH.
- Secure environment discovery in `config.py`:
  1. Check `MINIME_CONFIG_PATH` env variable if set.
  2. Check `MINIME_ENV_FILE` env variable if set.
  3. Check `/etc/minime/minime.env` if file exists and is readable.
  4. Check `.env` in working directory.
  5. Safely parse `KEY=VALUE` without executing code and inject into `os.environ.setdefault`.
- Host permissions:
  - `/etc/minime/minime.env` permissions set to `0640 minime:minime`.
  - Operator `silverman` added to group `minime`.
  - Production launcher `/usr/local/bin/minime` and `/usr/local/bin/minime-console` added to PATH.

## 4. Responsive Layout Design
- **Desktop (>= 1366px, 1920px, 2560px)**: 2-column master/detail layout with sticky action toolbar, tabs navigation, and rich stat grids.
- **Tablet (768px - 1024px)**: Fluid split-view or full-height detail drawer with touch-accessible buttons (>= 44px height).
- **Mobile (< 768px)**: Card-based vertical stack with sticky bottom navigation (Overview, Runs, Queue, Preview), emphasizing blockers and gates.
