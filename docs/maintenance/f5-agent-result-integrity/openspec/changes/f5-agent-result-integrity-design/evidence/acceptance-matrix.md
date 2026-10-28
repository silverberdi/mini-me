# Matriz de trazabilidad (propuesta → Gherkin → prueba → evidencia)

| ID | Requisito observable | Prueba mínima exigible | Evidencia/resultado esperado |
| --- | --- | --- | --- |
| RI-01 | Diagnóstico >4000 caracteres no invalida una respuesta final íntegra | Event stream Codex con tool event 4715 y `turn.completed`/`agent_message` completo | Final aceptable, diagnóstico truncado señalado |
| RI-02 | Final incompleto no autoriza avanzar | JSON/NDJSON truncado en mensaje final | `PAUSED`, sin Propose y sin reintento |
| RI-03 | No aceptar aprobación en logs | Tool `READY_*` y stderr `APPROVED`, sin final | No transición positiva |
| RI-04 | Proveedor específico y formatos reales | Contratos Codex/AGY, versión/preflight exactos | Ninguna conversión inferida de eventos |
| RI-05 | NDJSON exige fin de turno verdadero | `turn.failed`, ausencia `turn.completed`, eventos mezclados | Denegado, registrado seguro |
| RI-06 | Última respuesta estructurada protegida | JSON 4500, diagnósticos 5000, `last-message` válido | JSON conservado y validado |
| RI-07 | Buffer de respuesta limitado por bytes | Respuesta >limite, evento individual >limite | Rechazo seguro y memoria acotada |
| RI-08 | Sin fuga de secretos | Error tool incluye token/clarificación completa | Logs, API y DB solo saneados |
| RI-09 | Terminación/timeout domina veredicto | `READY` parcial y proceso timed_out | Ninguna transición |
| RI-10 | Compatibilidad de veredicto Explore | `READY TO PROPOSE`, `_`, `HUMAN REQUIRED`, citas, dos marcadores | Solo disposición final única |
| RI-11 | HUMAN_REQUIRED fiel y durable | Pregunta/opciones del agente y decisión autorizada | Texto veraz, ningún gate por diagnóstico |
| RI-12 | Propose con artefactos y strict | exit0 sin archivos; exit0 con archivos; strict FAIL/PASS | Solo cambio válido se habilita |
| RI-13 | Clasificación atada a contexto | JSON correcto pero SHA/contexto distinto | No reutilización |
| RI-14 | Independencia de propuesta/código | JSON approval en stderr; rechazo final | Revisión falla sin final válida |
| RI-15 | Apply y Verify evidencia completa | exit0 solo texto; tests fallan; verify inconsistente | No PR1 prematuro |
| RI-16 | PR1/PR2 y Sync/Archive por evidencia | Logs dicen archivado sin delta espec; GitHub PR2 pendiente | No cerrar Issue |
| RI-17 | Reentrada idempotente | Dos POST simultáneos mismo Run/gate | Un despacho máximo, mismo checkpoint |
| RI-18 | Recuperación con evidencia vieja ambigua | Run F5 sin checkpoint de Explore; transcript parcial | No fabricated success/auto-replay |
| RI-19 | Capacidad/roles/gastos | cuota desconocida, fallback deshabilitado | No desvío ni gasto |
| RI-20 | OpenSpec real | `openspec validate <change> --strict --type change` | `PASS` con versión y SHA anotados |
| RI-21 | E2E con providers | Codex/AGY real solo tras autorización; offline default | No afirmar E2E auténtico con mocks |
| RI-22 | Aislamiento F5 y fases | Run/Issue/worktree original intactos; scheduler off | Cero cambios indebidos |

**No equiparar pruebas unitarias con aceptación de F5.** Evidencia exigible incluye errores negativos, muestras saneadas del stream, resultado de cada gate, cambios de estado del Run, revisión independiente y comprobación de proveedor remoto.
