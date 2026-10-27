# Censo de lectura — contrato de respuestas en main

**Referencia:** `silverberdi/mini-me`, `main` observado en `fdc97430741697ab9ca4e3485330386eea5cd1c2` al momento del análisis. Esta es lectura de GitHub, **no una inspección del servidor Ubuntu**, y no asegura que no haya consumidores dinámicos indirectos.

| Ruta / contrato | Hecho observado | Riesgo / acción especificada |
| --- | --- | --- |
| `services/agent_confinement.py` / `run_confined_async_subprocess` | Obtiene `stdout` y `stderr` binarios, registra timeout, aplica scrub de credenciales antes de retornar. | Preservar protección; auditar memoria al acumular eventos completos y capacidad de retorno al runner. |
| `services/agent_runner.py:80–90` `AgentExecutionResult` | `response_output` = `structured_output` cuando existe, de lo contrario `stdout`; `full_output` mezcla stdout+stderr. | Identificar explícitamente autoridad por fuente, no mezclar diagnóstico con decisión. |
| `services/agent_runner.py:544–594` | `MAX_OUTPUT_LINES=2500`, `MAX_LINE_CHARS=4000`; detecta exceso, trunca líneas y mantiene `output_truncated`; el canal de último mensaje se lee íntegro hasta `MAX_STRUCTURED_OUTPUT_BYTES=1048576`. | Causa directa del rechazo observado; no cambiar solo umbral. |
| `tests/test_f4_structured_output.py` | Test de JSON nativo 4500 caracteres con diagnósticos 5000: `output_truncated=True`, respuesta íntegra válida. | Contrato parcial preexistente contradice uso indiscriminado de flag en Explore. |
| `services/orchestration_coordinator.py` normalización F4 | Persiste intento y último mensaje normalizado validado, distingue la publicación GitHub. | Reutilizar idempotencia y respuesta estructurada; evitar segunda normalización. |
| `...:1050–1145` | Reentrada Explore guarda `explore_checkpoint` con hash de contexto/respuesta; solo verifica forma de SHA al reutilizar. | Revisión de vinculación con evidencia fuente, intento y workflow. |
| `...:2320–2459` `_run_explore` | Usa `res.output_truncated` global; extrae eventos NDJSON `agent_message` / `turn.completed` desde `response_output`, parsea tokens finales. | Truncación diagnóstica bloquea; falta compatibilidad de tokens con spec F3; evaluar integridad real del evento. |
| `...:2485–2528` `_run_propose` | Acepta `_execution_is_successful` y pasa a validador; posterior `openspec validate` sí existe. | Verificar artefactos originados por workflow, esquema, proveeduría y pruebas. |
| `...:2180–2310` `_assess_complexity` | Respuesta última/schema y persistencia de evaluación, rechaza salida estructurada faltante/excesiva. | Conservar sin deshacer guardas; asegurar fuente/diagnóstico desacoplados. |
| `...:2530–2560` `_run_proposal_review` | `parse_review_verdict(res.full_output)` combina stdout y stderr. | Riesgo de contaminación, negar aceptación sin respuesta final. |
| `...:2559–2645` `_run_apply` | `exit_code`/evidencia general; pruebas automatizadas posteriores. | Asegurar evidencia nativa, SHA y pruebas, sin equiparar salida de agente a resultado. |
| `...:2645–2712` `_run_verify` | Utiliza output de último mensaje estructurado y validación de veredicto. | Mantener excepción correcta: logs truncados no invalidan respuesta final íntegra. |
| `...:2710–2745` `_run_code_review` | `parse_review_verdict(res.full_output)` con mezcla de stderr. | Riesgo de aprobar/rechazar por contenido de diagnósticos. |
| `...:2745–2815` `_run_sync_and_archive` | Verifica éxito de agente y cambios Git antes del cierre. | Exigir evidencias CLI/archivos/autoridad del PR2, no sólo transcript positivo. |
| `adapters/openspec.py` | `validate_change_strict` invoca `openspec validate <change> --strict --type change` y comprueba returncode. | Gate formal requerido; no confundir éxito CLI con corrección integral. |
| `openspec/specs/openspec-native-propose/spec.md` | Dicta salida `READY TO PROPOSE` y `HUMAN REQUIRED`. | Diferencia observable con `READY_TO_PROPOSE` del parser #194. |
| `openspec/specs/openspec-orchestration-continuity/spec.md` | Prohíbe perder Run/worktree, repetir efectos externos, inventar opciones humanas y liberar lock antes de cierre. | Reentrada debe seguir el mismo checkpoint; detener sin reintento automático si resultado ambiguo. |

**Observaciones que son hipótesis hasta verificación real:** impacto exacto de Antigravity en stdout; si la última llamada del 27-10 terminó emitiendo un mensaje final íntegro; si todos los consumers antiguos siguen alcanzables en F5; límites reales de eventos y tamaño de respuesta segura; contención entre dos llamadas API simultáneas. La implementación debe resolver estas incógnitas con lectura/fixtures y registrar el resultado antes de tocar código.
