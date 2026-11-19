# Proposal: Despacho Nativo de Actualización y Recuperación de Propuestas tras Revisión Independiente

## 1. Contexto y Problema

En cambios de complejidad Alta bajo el Contrato Rector 2.0 (ej. Issue #3 de `multiplo`), la propuesta OpenSpec pasa por una revisión independiente de arquitectura obligatoria. Cuando el revisor emite hallazgos sustantivos (`CHANGES_REQUIRED`) y el operador resuelve el gate humano de escalación solicitando la corrección (`pending_proposal_revision`), el orquestador reingresa a la etapa `PROPOSING` para que el agente de pensamiento ajuste los artefactos.

Sin embargo, el coordinador de orquestación presentaba tres defectos de gobernanza y despacho que causaban un bloqueo persistente en producción:
1. **Despacho del workflow incorrecto**: `_run_propose` despachaba la operación `continue` (`openspec-continue-change`) para artefactos que ya existían completamente (`proposal.md`, `specs/`, `design.md`, `tasks.md`). Al no haber archivos pendientes por crear, el comando `continue` reportaba `INCOMPLETE`, provocando un fallo técnico de la invocación. El workflow oficial para revisar artefactos ya articulados es `openspec-update-change` (`update`).
2. **Rechazo de invocación por falta de autorización de reintento**: En `_run_native_dispatch`, la bandera `authorized_retry` se evaluaba como `propose_recovery_needed and not pending_revision`, resultando en `False` cuando existían revisiones pendientes. Como el intento anterior se registró como `FAILED` sobre el mismo candidato de Git, `_begin_stage_invocation` rechazaba la ejecución y retornaba `None`.
3. **Bloqueo de claim distribuido por excepción no controlada**: Al retornar `_begin_stage_invocation` `None`, se levantaba `RuntimeError("Propose stage invocation is already active or ambiguous")` antes de registrar el resultado de la acción externa, dejando el claim de PostgreSQL (`run:<run_id>`) activo sin liberar. Esto provocaba un bucle de bloqueo de 90 segundos que alternaba entre *"Propose dispatch is already owned"* y *"Propose stage invocation is already active or ambiguous"*.

## 2. Alcance Propuesto

1. **Despacho del workflow oficial `update`**:
   - En `NativeOrchestrationCoordinator._run_propose`, verificar si existe `pending_revision` o si los artefactos de la propuesta ya están completos. Si es así, resolver y despachar la operación `update` (`openspec-update-change`) con un prompt contextual que incluya los hallazgos del revisor independiente y las aclaraciones del operador.
2. **Habilitación de reingreso autorizado en el guardián de invocaciones**:
   - En `_run_native_dispatch`, pasar `authorized_retry=True` y `allow_human_resume=True` cuando existan revisiones pendientes de propuesta (`pending_proposal_revision`), permitiendo que `_begin_stage_invocation` acepte la re-ejecución sobre el mismo candidato.
   - En `_begin_stage_invocation`, permitir la reanudación cuando `authorized_retry` o `allow_human_resume` estén activos aun si el estado previo del candidato fue `COMPLETE` o `FAILED`.
3. **Liberación estricta y segura de claims distribuidos**:
   - En `_run_native_dispatch`, si `invocation is None`, finalizar y liberar formalmente el claim de despacho (`_finish_native_dispatch`) antes de registrar la pausa o levantar la excepción, evitando la fuga del lease de 90 segundos.
4. **Verificación unitaria y de integración**:
   - Crear pruebas unitarias que verifiquen el ciclo completo de reingreso a `PROPOSING` con `pending_proposal_revision`: despacho de `update`, autorización de `_begin_stage_invocation` y liberación de claims.

## 3. Fuera de Alcance

- Modificar la política de revisión independiente ni relajar los criterios de complejidad.
- Modificar el flujo de `apply`, `verify` o `doc_closing`.
- Crear generadores o modificadores de Markdown paralelos a las skills nativas de OpenSpec.
