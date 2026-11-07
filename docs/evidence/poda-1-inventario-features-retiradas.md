# PODA 1 — Inventario histórico de superficies y persistencia retiradas

**Issue:** [#316 (PODA 1: Retirar código y persistencia fuera de los flujos actuales de la UI)](https://github.com/silverberdi/mini-me/issues/316)  
**Change OpenSpec:** `req-316-poda-1-retirar-codigo-persistencia`  
**SHA Base de referencia:** `6b7a405` (tag `v0.1.55`)  
**Fecha:** 2026-11-07  
**Autoridad:** [CONTRATO_RECTOR.md](../../docs/CONTRATO_RECTOR.md) v2.0 (§1 La gacela, no el paquidermo; §7 Reglas de ingeniería; §11 Reconciliación del legado)

---

## 1. Línea base de pruebas pre-poda (SHA `6b7a405`)

Ejecución de la suite completa de pruebas sobre el SHA de partida antes de aplicar cualquier modificación:
- **Total tests evaluados:** 1095
- **Passed:** 1057
- **Failed:** 26 (errores preexistentes en mocks de orquestación `_git_run` / `stdout`)
- **Skipped:** 12
- **Tiempo de ejecución:** 227.63s
- **Criterio de no-regresión:** La suite post-poda debe mantener los tests de flujos activos en verde sin incrementar fallos en la funcionalidad preservada.

---

## 2. Mapa de superficies activas consumidas por la UI vigente

El censo estático realizado sobre `frontend/src/app/` identificó exclusivamente los siguientes contratos activos en la PWA Angular (Dashboard, Trabajo, Trabajo actual, Proyectos, Backlog y Administración de modelos):

| Método | Endpoint | Consumidor Frontend | Propósito UI |
|---|---|---|---|
| GET | `/api/v1/auth/me` | `auth.service.ts` | Estado de sesión del operador |
| POST | `/api/v1/auth/logout` | `auth.service.ts` | Cierre de sesión |
| GET | `/api/v1/auth/google/login` | `app.component.ts` | Inicio de login OAuth |
| GET | `/api/v1/projects` | `refresh.service.ts`, `admin-models.component.ts` | Lista de proyectos en Dashboard, Proyectos y Admin |
| POST | `/api/v1/projects` | `proyectos.component.ts` | Creación de proyecto |
| GET | `/api/v1/projects/{project_id}` | `admin-models.component.ts` | Detalle de proyecto |
| PATCH | `/api/v1/projects/{project_id}` | `proyectos.component.ts`, `admin-models.component.ts` | Configuración de agentes y modelos |
| POST | `/api/v1/projects/{project_id}/pause` | `proyectos.component.ts` | Pausa de ejecución del proyecto |
| POST | `/api/v1/projects/{project_id}/resume` | `proyectos.component.ts` | Reanudación de ejecución del proyecto |
| POST | `/api/v1/projects/{project_id}/connections/verify` | `proyectos.component.ts` | Verificación de conexión remota |
| GET | `/api/v1/projects/{project_id}/requests` | `refresh.service.ts` | Lista de tickets en Backlog |
| POST | `/api/v1/projects/{project_id}/requests` | `backlog.component.ts` | Creación de nuevo Request |
| POST | `/api/v1/projects/{project_id}/requests/run` | `backlog.component.ts`, `trabajo-actual.component.ts` | Admisión de Run / Respuesta de Human Gate |
| POST | `/api/v1/projects/{project_id}/requests/{num}/deactivate` | `backlog.component.ts` | Desactivación de Request |
| POST | `/api/v1/projects/{project_id}/requests/{num}/reactivate` | `backlog.component.ts` | Reactivación de Request |
| GET | `/api/v1/orchestration/runs` | `refresh.service.ts` | Lista y estado de runs para Trabajo y Trabajo actual |
| GET | `/api/v1/dashboard/overview` | `refresh.service.ts` | Métricas de efectividad y costos para Dashboard |
| GET | `/api/v1/providers/quotas` | `refresh.service.ts` | Medidores analógicos de cuota de proveedores |
| GET | `/api/v1/events` | `refresh.service.ts` | Server-Sent Events (SSE) para actualización en tiempo real |
| GET | `/api/v1/catalogs/agents` | `proyectos.component.ts`, `admin-models.component.ts` | Catálogo de roles de agentes |
| GET | `/api/v1/admin/providers/catalog` | `admin-models.component.ts` | Catálogo de proveedores y modelos |
| POST | `/api/v1/admin/providers/refresh` | `admin-models.component.ts` | Refresco de modelos descubiertos |
| PATCH | `/api/v1/admin/providers/models/{id}/enabled` | `admin-models.component.ts` | Habilitación/deshabilitación de modelos |
| POST | `/api/v1/admin/providers/{id}/test` | `admin-models.component.ts` | Diagnóstico de credenciales y conectividad |
| POST | `/api/v1/system/pause` | `trabajo.component.ts` | Pausa global de mini me |
| POST | `/api/v1/system/resume` | `trabajo.component.ts` | Reanudación global de mini me |
| GET/POST/DEL | `/api/v1/push/*` | `push-notification.service.ts` | Suscripciones Web Push del operador |

---

## 3. Inventario de superficies y persistencia retiradas (Poda)

Las siguientes superficies fueron auditadas y confirmadas con **0 consumidores** en la UI activa ni en la orquestación actual:

### 3.1. Rutas FastAPI retiradas (`src/minime/api/app.py`)

1. **APIs heredadas no versionadas (pre-v1):**
   - `GET /projects`
   - `GET /projects/{project_id}`
   - `GET /projects/{project_id}/changes`
   - `GET /projects/{project_id}/jobs`
   - `GET /providers/openrouter/status`
2. **Endpoints de Jobs históricos (modelo de ejecuciones de consola/TUI previo a OrchestrationRun):**
   - `GET /jobs/{job_id}`
   - `GET /jobs/{job_id}/logs`
   - `GET /jobs/{job_id}/review`
   - `GET /jobs/{job_id}/audit`
   - `GET /jobs/{job_id}/attempts`
   - `GET /jobs/{job_id}/blockers`
   - `GET /jobs/{job_id}/handoffs`
   - `GET /jobs/{job_id}/manifest`
   - `GET /jobs/{job_id}/diagnostics`
3. **Endpoints de Previews y Validaciones experimentales (pre-Angular F8):**
   - `GET /api/v1/previews/{preview_id}`
   - `GET /api/v1/previews/changes/{project_id}/{change_name}`
   - `GET /api/v1/validations/scenarios/{project_id}/{change_name}`
   - `GET /api/v1/validations/authority/{project_id}/{change_name}`
4. **Endpoints de métricas de tickets huérfanas:**
   - `GET /api/v1/projects/{project_id}/requests/{issue_number}/metrics`
   - `GET /api/v1/openspec/integrity`
5. **Endpoints de contexto/onboarding legacy:**
   - `GET /api/v1/projects/{project_id}/onboarding`
   - `POST /api/v1/projects/{project_id}/onboarding/observe-merge`
   - `POST /api/v1/projects/{project_id}/context/observe-merge`
   - `PATCH /api/v1/projects/{project_id}/context/document`
   - `POST /api/v1/projects/{project_id}/executor`
   - `POST /api/v1/projects/{project_id}/activate`
   - `GET /api/v1/catalogs/providers`

### 3.2. Tablas y Modelos SQLAlchemy desincorporados (`src/minime/db/models.py`)

1. `metric_facts`: Tabla de hechos métricos acumulados sin lectura en la UI.
2. `integrity_findings`: Hallazgos de integridad estructural sin consulta activa.
3. `jobs`: Entidad de ejecución previa al modelo canónico `orchestration_runs`.
4. `job_attempts`: Intentos de jobs del modelo anterior.
5. `blocker_claims`: Reclamos de bloqueos asociados al scheduler antiguo.
6. `job_handoffs`: Handoffs de jobs reemplazados por el ciclo de etapas de OrchestrationRun.
7. `candidate_manifests`: Manifiestos de candidatos heredados.
8. `candidate_authorships`: Autorías heredadas sustituidas por `reviews.is_mixed_authorship`.
9. `evidence_diagnostics`: Diagnósticos no vinculados a runs actuales.
10. `job_logs`: Registros de consola de jobs históricos.
11. `preview_sessions`: Sesiones de preview de contenedores sin consumidor.
12. `validation_runs`: Runs de validación sintética descontinuados.

---

## 4. Guía de recuperación histórica desde Git

Si en el futuro se requiriera reactivar o consultar el código original de alguna de estas características podadas, puede ser extraído directamente del historial inmutable de Git:

* **Commit de referencia:** `6b7a405` (HEAD de `main` pre-poda)
* **Comandos para inspeccionar servicios retirados:**
  ```bash
  git show 6b7a405:src/minime/services/container_preview_service.py
  git show 6b7a405:src/minime/services/openspec_integrity.py
  git show 6b7a405:src/minime/services/validation_authority_service.py
  ```
* **Comandos para inspeccionar pruebas retiradas:**
  ```bash
  git show 6b7a405:tests/test_candidate_validation_authority.py
  git show 6b7a405:tests/test_container_preview_acceptance.py
  git show 6b7a405:tests/test_container_preview_service.py
  git show 6b7a405:tests/test_openspec_integrity.py
  ```
* **Comando para inspeccionar las rutas eliminadas del router:**
  ```bash
  git show 6b7a405:src/minime/api/app.py
  ```
* **Comando para consultar la definición original de modelos SQLAlchemy:**
  ```bash
  git show 6b7a405:src/minime/db/models.py
  ```

---

## 5. Resultados de verificación y no regresión

- **Línea base pre-poda (SHA `6b7a405`):** 1057 passed, 26 failed (mock errors preexistentes en `_stage_candidate_identity`), 12 skipped (total: 1095).
- **Línea post-poda (Change actual):** 1034 passed, 26 failed (mismos mock errors preexistentes en `_stage_candidate_identity`), 11 skipped (total: 1071).
- **Diferencial de tests:** 24 tests retirados correspondían exclusivamente a los 4 archivos de prueba podados (`test_candidate_validation_authority.py`, `test_container_preview_acceptance.py`, `test_container_preview_service.py` y `test_openspec_integrity.py`). Se retiró además 1 paso de prueba del endpoint huérfano `/metrics` en `tests/test_f7_functional_operations.py`, y se incorporaron 2 nuevos tests de verificación de invariantes en `tests/test_postgres_state.py`.
- **Regresiones en flujos vigentes:** **0**. Todas las pruebas de Dashboard, Proyectos, Backlog, Model Admin, Proveedores, PWA y Autenticación se ejecutaron con éxito.
- **Validación OpenSpec:** `openspec validate req-316-poda-1-retirar-codigo-persistencia` aprobado sin errores.
- **Validación Alembic:** Generación DDL offline (`alembic upgrade head --sql` y `alembic downgrade poda01_retire_orphaned_persistence:f14_provider_model_enablement --sql`) exitosa demostrando `DROP TABLE` limpio con downgrade simétrico disponible.
- **Validación de preflight de invariantes:** Verificado mediante `test_verify_physical_schema_invariants_valid` y `test_verify_physical_schema_invariants_mismatch`.

---

## 6. Métricas cuantitativas del cambio

- **Archivos modificados/retirados:** 15 archivos de código y pruebas (+ 2 archivos de inventario y migración).
- **Líneas de código y pruebas retiradas:** -2,706 líneas en el código base.
- **Líneas netas agregadas:** +39 líneas (migración Alembic simétrica y adaptadores no-op de compatibilidad).
