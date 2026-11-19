# Design: Spanish Independent Review Findings & Unblocked Proposal Review Dispatch

## Context & Architecture
El orquestador de mini me (`NativeOrchestrationCoordinator`) coordina las etapas de propuesta, revisión independiente y ejecución.
El Contrato Rector 2.0 y las directrices de UX establecen que los gates humanos deben comunicarse en español simple sin exponer salidas crudas en otros idiomas.
Asimismo, el ciclo de vida de la propuesta debe avanzar fluidamente entre la revisión de la propuesta por el revisor independiente y las correcciones del pensador, sin caer en interbloqueos duraderos causados por clasificaciones falsamente ambiguas.

## Component Changes

### 1. `src/minime/services/orchestration_coordinator.py`
- **`_REVIEW_VERDICT_SCHEMA_HINT`**:
  Añadir directriz obligatoria de idioma:
  `"Todo resumen ('summary'), requisito infringido ('violated_requirement') y corrección esperada ('expected_correction') debe redactarse obligatoriamente en español simple, claro y conciso."`
- **`_run_proposal_review` y `_run_code_review`**:
  Incluir explícitamente en el prompt del revisor la instrucción de redactar todos los campos de texto en español simple, apto para el operador humano.
- **`_classify_review_reentry`**:
  Cuando `stored is None`:
  Si no hay evidencia duradera de revisión previa, retornar `_REVIEW_STALE` para permitir el despacho limpio de la revisión en lugar de forzar `_REVIEW_AMBIGUOUS` en reanudación, preservando la seguridad de que un review ya completado no se ignore.
- **Invocación de `PROPOSAL_REVIEW` en `_execute_run_internal`**:
  Garantizar que `_begin_stage_invocation(uow, active_run, worktree_path, "PROPOSAL_REVIEW", allow_human_resume=True, ...)` permita la reentrada a la etapa cuando la propuesta viene de una revisión o autorización del operador.

### 2. Pruebas Unitarias
- `tests/test_reviewer_spanish_and_proposal_review_dispatch.py`:
  - Verificar que el schema hint y los prompts de revisión contienen la exigencia de español simple.
  - Verificar que `_classify_review_reentry` retorna `_REVIEW_STALE` cuando `stored is None` en reanudación.
  - Verificar que `_begin_stage_invocation` permite la reevaluación de la propuesta tras revisión autorizada.
