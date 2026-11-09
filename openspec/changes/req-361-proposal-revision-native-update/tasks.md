# Tasks

## 1. Despacho del workflow oficial `update` para revisiones de propuesta

- [x] 1.1 Modificar `NativeOrchestrationCoordinator._run_propose` para admitir `pending_revision: bool = False` o detectar `pending_proposal_revision`, resolviendo y despachando la operación `update` (`openspec-update-change`) en lugar de `continue`.
- [x] 1.2 Formular el prompt de despacho de `update` incorporando las observaciones del revisor independiente y la aclaración del operador.

## 2. Gobernanza de reingreso y liberación de claims

- [x] 2.1 Actualizar la llamada a `_run_native_dispatch` en la etapa `PROPOSING` para pasar `authorized_retry=True` y `allow_human_resume=True` cuando existan revisiones pendientes (`pending_proposal_revision`).
- [x] 2.2 Modificar `_begin_stage_invocation` para permitir la re-ejecución sobre el mismo candidato de propuesta cuando `authorized_retry` o `allow_human_resume` estén activos aun si el intento anterior terminó en `COMPLETE` o `FAILED`.
- [x] 2.3 Modificar `_run_native_dispatch` para que si `invocation is None`, se llame a `_finish_native_dispatch` liberando el claim antes de fallar.

## 3. Pruebas y validación

- [x] 3.1 Crear prueba unitaria en `tests/test_proposal_revision_update_dispatch.py` que compruebe que ante `pending_proposal_revision` se resuelve y ejecuta `openspec-update-change`, no se bloquea en `_begin_stage_invocation` y se liberan claims limpiamente.
- [x] 3.2 Ejecutar la suite completa de pruebas unitarias y de gobernanza para asegurar 0 regresiones.
