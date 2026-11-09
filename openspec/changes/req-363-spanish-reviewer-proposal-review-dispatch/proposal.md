# Proposal

## Problem Statement
En flujos de alta complejidad, las revisiones independientes (de propuesta y de código) presentaron dos defectos materiales observados en producción:
1. **Spanglish en gates para el operador**: El prompt del revisor independiente y el schema hint no exigían que el veredicto, resumen y hallazgos estuvieran en español. Como consecuencia, el revisor independiente (`opencode` / DeepSeek) redactó los hallazgos en inglés técnico, exponiéndolos directamente en el modal `HUMAN_REQUIRED` del operador humano y violando el principio del Contrato Rector de presentar gates en español simple y directo.
2. **Pausa espuria por ambigüedad al reevaluar la propuesta**: Al entrar o reanudar `PROPOSAL_REVIEW` tras una revisión o corrección de propuesta sin un registro previo duradero de revisión, `_classify_review_reentry` clasificaba la ausencia de registro en reanudación como `_REVIEW_AMBIGUOUS`, marcando el run como `PAUSED` y exigiendo autorización de recuperación espuria en lugar de despachar la revisión fresca. Además, `_begin_stage_invocation` requería `allow_human_resume=True` para permitir la reentrada a la etapa.

## Proposed Solution
1. **Exigencia de español simple en prompts y schema del revisor**:
   - Actualizar `_REVIEW_VERDICT_SCHEMA_HINT` para especificar de forma obligatoria que `summary`, `violated_requirement` y `expected_correction` deben redactarse en español simple, claro y conciso.
   - Ajustar los prompts de revisión de propuesta (`_run_proposal_review`) y revisión de código (`_run_code_review`) para ordenar la redacción íntegra en español.
2. **Despacho limpio de reevaluación de propuesta**:
   - Ajustar `_classify_review_reentry` para que la ausencia de revisión duradera (`stored is None`) se trate como `_REVIEW_STALE` (lista para despacho) permitiendo que el orquestador ejecute la revisión pendiente sin pausas espurias.
   - Pasar `allow_human_resume=True` a `_begin_stage_invocation` al despachar `PROPOSAL_REVIEW` tras una revisión o corrección de propuesta.
3. **Pruebas deterministas**:
   - Agregar pruebas unitarias que verifiquen la inclusión de la instrucción en español en los prompts y schema del revisor.
   - Agregar pruebas que verifiquen que la reentrada a `PROPOSAL_REVIEW` sin review previo se clasifica para despacho fresco y que la invocación no se bloquea.
