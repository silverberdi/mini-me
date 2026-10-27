## Why

F5 (Issue #173, único Change ejecutable `gacela-05-ui-self-hosted`) está detenido en `EXPLORING` después de tres correcciones de integración, porque la infraestructura confunde truncación de diagnósticos con integridad de la respuesta final. En la reanudación del 27-10-2026 se consumió una invocación Codex, el Run permaneció en `EXPLORING` y no se generaron artefactos F5. La causa observada fue un evento NDJSON de más de 4.000 caracteres por la aclaración humana, que activó el indicador global `output_truncated` antes de interpretar el veredicto. No está probado que la respuesta final de esa ejecución fuera recuperable; tampoco está probado que requiera repetir la inferencia.

El fallo no se limita a Explore: normalización, clasificación y Verify ya utilizan un canal de respuesta estructurada, mientras Explore extrae mensajes de NDJSON y ciertos revisores interpretan `full_output`, que mezcla `stdout` y `stderr`. Esta asimetría afecta a la seguridad de transiciones, cuota, recuperación y evidencia. Aumentar `MAX_LINE_CHARS`, ignorar una bandera o crear una nueva capa de agentes no resuelve el contrato común.

## What Changes

- Precisar el contrato **compartido de evidencia de ejecución** en el `CliAgentRunner` existente: distinguir resultado final autoritativo y completo, diagnósticos truncables e integridad/categoría de ejecución. No introducir otro runner, cola, controlador de workflows, proveedor ni DB paralela.
- Establecer extracción de respuesta de acuerdo con las capacidades verificadas de Codex y Antigravity: aprovechar el canal nativo de última respuesta/JSON cuando exista; en NDJSON, separar eventos de herramientas y mensajes de agente completos sin perder verificación de fin de turno; no tomar la mera presencia de un token en logs como autorización de etapa.
- Alinear **todos los consumidores alcanzables**: normalizador F4, Explore, Propose, clasificación de complejidad, revisión independiente de propuesta, Apply, Verify, revisión de código, preparación de PR, Sync y Archive. Cada etapa requiere evidencia apropiada para su autoridad; `exit_code=0` por sí solo nunca equivale a aceptación de contenido o artefactos.
- Reconciliar el protocolo contractual `READY TO PROPOSE` / `READY_TO_PROPOSE` con una representación canónica documentada y compatibilidad comprobada, sin interpretar alusiones textuales, citas, tool logs ni múltiples veredictos.
- Reutilizar el Run, el worktree, las autorizaciones y el estado PostgreSQL existentes; definir checkpoints autenticables mediante evidencia de origen, hashes de contexto, workflow, modelo y resultado, transición exacta y operación idempotente. No inventar evidencia retroactiva de las ejecuciones ya realizadas.
- Cubrir errores adversariales, tamaño/líneas del flujo, cierre/cancelación del proceso, diagnóstico sensible, doble despacho, errores de GitHub y la cadena nativa OpenSpec hasta PR1/PR2 con pruebas deterministas y E2E controlado antes de permitir una nueva autoejecución F5.

## Capabilities

### New Capabilities

- `agent-result-evidence-integrity`: contrato de separación de respuesta autoritativa, diagnóstico, integridad de transporte y confianza de transición, aplicado sobre el runner y almacenamiento ya existentes; **nueva especificación de comportamiento, no nuevo motor de software**.

### Modified Capabilities

- `openspec-native-propose`: evidencia terminal y protocolo fiel de Explore → Propose, preservando ejecución real del workflow.
- `openspec-orchestration-continuity`: checkpoint duradero, decisiones humanas y recuperación sin llamadas duplicadas ni autorizaciones sintéticas.

## Impact

- **Alcance inicial localizado por lectura:** `src/minime/services/agent_runner.py` (`AgentExecutionResult`, `CliAgentRunner.run`); `src/minime/services/orchestration_coordinator.py` (normalización, `_run_explore`, `_run_propose`, `_assess_complexity`, `_run_proposal_review`, `_run_apply`, `_run_verify`, `_run_code_review`, `_run_sync_and_archive`, preparación de PR); `src/minime/services/agent_confinement.py` (captura/saneamiento); `src/minime/services/review_verdict_parser.py`; `src/minime/adapters/openspec.py`; pruebas existentes de F3/F4/F5.
- **Restricciones:** sin modificación del scheduler, admisión FIFO, CRUD F7, UI F8, nuevos modelos, pagos, migración, secreto ni despliegue. Sin reabrir F1–F4. El Issue #173 y su Run conservan identidad; los PR #192–#194 no se revierten automáticamente.
- **Gobernanza del borrador:** preparación documental autorizada; **NO** se activa un nuevo Change en `silverberdi/mini-me`, no se modifica `gacela-05-ui-self-hosted`, no se implementa, no se fusiona, no se despacha agente. Este nombre de Change es exclusivamente una envoltura para validar formalmente el borrador en un checkout desechable. La ubicación definitiva y autoridad de incorporación al único Change F5 requieren aprobación expresa antes de la implementación.
- **Criterios de aceptación:** OpenSpec CLI strict real PASS en un checkout aislado; revisión arquitectónica y de trazabilidad; tests deterministas/e2e con salidas reales o fixtures identificados; ningún modelo real para pruebas que puedan ser offline; ejecución F5 exclusivamente tras autorización y restauración segura del checkpoint.