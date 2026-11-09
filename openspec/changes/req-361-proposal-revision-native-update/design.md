# Design: Despacho Nativo de Actualización y Recuperación de Propuestas

## 1. Arquitectura y Componentes

El cambio corrige la máquina de estados y el subsistema de despacho nativo en `NativeOrchestrationCoordinator` ([`src/minime/services/orchestration_coordinator.py`](file:///Users/silveriobernal/documents/code/development/mini-me/src/minime/services/orchestration_coordinator.py)).

### 1.1 Resolución de Workflow en `_run_propose`
Actualmente:
```python
operation = "continue" if continue_existing else "propose"
```
Nuevo diseño:
```python
if pending_revision:
    operation = "update"
elif continue_existing:
    operation = "continue"
else:
    operation = "propose"
```
Cuando `operation == "update"`:
- Resuelve `openspec-update-change` (`.agent/workflows/opsx-update.md` para Antigravity o `.agents/skills/openspec-update-change/SKILL.md` para Codex).
- Elabora un prompt contextual claro:
  ```text
  Execute official OpenSpec Update for change '{change_name}'.
  Workflow dispatch command: {wf.dispatch_command}
  ...
  Update the existing planning artifacts under openspec/changes/{change_name}/ to address the independent review findings:
  {operator_clarification}
  ```

### 1.2 Autorización de Reintento y Reingreso
En el paso 4 del coordinador (`OrchestrationStage.PROPOSING`):
```python
allow_human_resume = bool(
    (verified_propose_human_gate and operator_clarification) or pending_revision
)
authorized_retry = bool(
    (propose_recovery_needed and not pending_revision) or pending_revision
)
```
Y en `_begin_stage_invocation`:
```python
if prior_finished:
    last_status = prior_finished[-1]
    if last_status == "COMPLETE" and not (authorized_retry or allow_human_resume):
        return None
    if last_status == "HUMAN_REQUIRED" and not allow_human_resume:
        return None
    if last_status in {"FAILED", "PARTIAL"} and not (
        authorized_retry or (stage == "APPLY" and last_status == "PARTIAL")
    ):
        return None
```
Esto permite que una propuesta que ya finalizó (`COMPLETE`) o que falló en un intento previo (`FAILED`) pueda ser revisada y actualizada cuando el operador o el revisor independiente autorizaron la corrección.

### 1.3 Liberación Limpia de Claims de Despacho
En `_run_native_dispatch`:
```python
invocation = await self._begin_stage_invocation(
    uow, run, worktree_path, operation.upper(),
    allow_human_resume=allow_human_resume,
    authorized_retry=authorized_retry,
)
if invocation is None:
    self._finish_native_dispatch(
        uow, run, operation, attempt_id, action_key, claim, "AMBIGUOUS",
        f"{operation.title()} stage invocation is already active or ambiguous"
    )
    raise RuntimeError(f"{operation.title()} stage invocation is already active or ambiguous")
```
Al invocar `_finish_native_dispatch`, se marca la acción externa y se libera el claim distribuido `claim` en `uow.claims.release_claim(claim)`, evitando que el scheduler quede esperando 90 segundos por la expiración del lease.
