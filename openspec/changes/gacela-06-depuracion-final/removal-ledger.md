# F6 Removal Ledger

Estado: `COMPLETE` — inventario final, reconciliación del fixture y pruebas post-retiro concluidas.

## Candidate identity and workflow trace

| Campo | Evidencia observada |
|---|---|
| Issue / Change | #174 / `gacela-06-depuracion-final` |
| Worktree | `/opt/minime/repos/mini-me/.minime/worktrees/request-174-f6-depuración-final-ejecutada-por-mini-m` |
| Branch | `request-174-f6-depuración-final-ejecutada-por-mini-m` |
| Base / Candidate SHA | `82748f465b560ea41159f76ad98fe9b8c6d80b3a` / `8c620c995a152f3979fbb37a8021fc9a63f025b8` |
| Workflow | `openspec status` + `openspec instructions apply`; schema `spec-driven` |
| Store | local nearest repo |

## Classification

| Área / candidato | Clasificación | Evidencia y razón |
|---|---|---|
| Native OpenSpec CLI and current Change artifacts | REUSE | CLI reporta ready, 18 tareas y artefactos completos. `openspec validate` exitoso. |
| FastAPI F2–F5 services, adapters, bindings, jobs, claims, budgets and candidate evidence | RETAIN-WITH-REASON | Son autoridades de continuidad necesarias para el funcionamiento de mini me. |
| `/scheduler/status`, `/api/v1/scheduler/*`, `/api/v1/queue/*` rejection/observability routes | RETAIN-WITH-REASON | Contratos F1/F3 de rechazo explícito (410/503) cubiertos por tests de regresión. |
| Historical Alembic revisions, including F1/F2 retirement migrations | RETAIN-WITH-REASON | Migraciones aplicadas e historia durable conservada; `alembic heads` devuelve `f2_retire_project_legacy_context`. |
| `mini-me-fixture` / `silverberdi/mini-me-r01-e2e-20261014` | REMOVED & RECONCILED | Respaldo inmutable verificado en `/opt/minime/repos/mini-me-r01-e2e-fixture-backup.bundle` (30 referencias). Autorización humana expresa otorgada. Repositorio eliminado de GitHub con verificación autoritativa de ausencia (HTTP 404 / NOT_FOUND). Proyecto `mini-me-fixture` marcado como `RETIRED` en PostgreSQL y binding invalidado. |
| F7/F8, deployment, scheduler activation | REMOVE FROM F6 SCOPE | Confirmados fuera de alcance por contrato rector v1.3; no se ejecutan ni se añaden. |

## Verification and proof

- **Project test suite**: `pytest -q -k "not acceptance and not orchestration_acceptance"` → 944 passed, 17 skipped, 0 failed (exit code 0).
- **Process safety suite**: `pytest tests/test_process_safety.py` → 10 passed, 0 failed (exit code 0).
- **Code style & lint**: `ruff check .` → All checks passed (exit code 0).
- **OpenSpec validation**: `openspec validate gacela-06-depuracion-final` → Change is valid, 4/4 artifacts complete.
- **Fixture backup bundle**: `/opt/minime/repos/mini-me-r01-e2e-fixture-backup.bundle` verificado con `git bundle verify` (30 referencias, OK).
- **GitHub authoritative absence check**: `GitHubAdapter.verify_repository("silverberdi/mini-me-r01-e2e-20261014")` → `outcome=FAILURE, reason_code=NOT_FOUND, data=False` (HTTP 404 confirmado).
- **PostgreSQL reconciliation**: proyecto `mini-me-fixture` actualizado a `status="RETIRED"`, binding `is_valid=False`, `mismatch_reasons=["FIXTURE_RECONCILED_AND_RETIRED_F6"]`.
