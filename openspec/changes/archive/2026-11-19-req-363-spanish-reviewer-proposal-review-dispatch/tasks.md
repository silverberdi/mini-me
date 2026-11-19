# Tasks

## 1. Spanish Language Enforcement in Reviewer Prompts
- [x] 1.1 Actualizar `_REVIEW_VERDICT_SCHEMA_HINT` en `src/minime/services/orchestration_coordinator.py` para obligar a que `summary`, `violated_requirement` y `expected_correction` se redacten en español simple.
- [x] 1.2 Actualizar los prompts de revisión de propuesta (`_run_proposal_review`) y de código (`_run_code_review`) en `orchestration_coordinator.py` ordenando explícitamente la redacción en español simple.

## 2. Unblock Proposal Review Dispatch on Reentry
- [x] 2.1 Actualizar `_classify_review_reentry` en `orchestration_coordinator.py` para tratar la ausencia de revisión duradera (`stored is None`) como `_REVIEW_STALE` en reanudación y entrada a etapa, evitando la falsa clasificación `_REVIEW_AMBIGUOUS`.
- [x] 2.2 Asegurar que en `_execute_run_internal` para `PROPOSAL_REVIEW`, `_begin_stage_invocation` reciba `allow_human_resume=True` cuando la propuesta provenga de una revisión autorizada o resolución de gate.

## 3. Pruebas y Validación
- [x] 3.1 Agregar pruebas unitarias en `tests/test_reviewer_spanish_and_proposal_review_dispatch.py` para verificar los prompts en español y la clasificación de reentrada.
- [x] 3.2 Ejecutar la suite completa de pruebas relacionadas y validar estrictamente el cambio OpenSpec.
