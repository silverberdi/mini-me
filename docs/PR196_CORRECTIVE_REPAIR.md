# PR #196 — reparación correctiva del ejecutor

## Autoridad y alcance

El operador autorizó esta excepción de mantenimiento correctivo para desbloquear la ejecución autónoma de F5. PR #196 no es una fase ni un Change OpenSpec, no cambia el alcance funcional de F5 y no modifica su Run, Change, worktree, PostgreSQL productivo, scheduler o proveedores.

La trazabilidad es: autorización del operador → hallazgos Antigravity F1–F10 → esta matriz → Removal Ledger → pruebas → revisión independiente del SHA final.

## Matriz de aceptación

| Hallazgo | Disposición | Invariante protegida | Evidencia requerida |
|---|---|---|---|
| F1 | Delegar estado a OpenSpec y pausar ante UNKNOWN | Nunca redispatch sin autorización | regresión VALIDATING + UNKNOWN |
| F2 | Reutilizar RecoveryClaim y renovar mientras vive el worker | Un único despacho por intento | PostgreSQL: lease/heartbeat/concurrencia |
| F3 | Documentar esta excepción y no crear Change | Alcance gobernado | diff, contrato y este registro |
| F4 | Conservar watchdog; terminar solo por causa explícita verificable | Silencio no equivale a bloqueo | watchdog + proceso prolongado |
| F5 | Reutilizar ExternalActionType existente | Cero enums/tablas/migraciones nuevas | importación y prueba PostgreSQL |
| F6 | Redactar en el único punto de salida humana | No persistir secretos | prueba HUMAN_REQUIRED |
| F7 | Consumir autorización en la misma transacción que reserva despacho | Una autorización, un intento | prueba de rollback/preparación fallida |
| F8 | Timeout solo para `openspec status` | Agente sin límite global arbitrario | prueba TimeoutExpired |
| F9 | Compartir camino técnico Explore/Propose | Un dueño de despacho | pruebas de ambos workflows |
| F10 | Retirar compatibilidad redundante donde no proteja historia | Una fuente de verdad | diff y regresión focalizada |

## Removal Ledger

| Ruta | Disposición | Razón |
|---|---|---|
| `planning_status` como heurística de ejecución | MANTENER como observación oficial OpenSpec | autoridad de completitud, no de despacho |
| chequeo de archivos para handoff nuevo | RETIRAR progresivamente; conservar solo legado verificable | evita segunda fuente de verdad |
| `ExternalActionType.OPENSPEC_PROPOSE_DISPATCH` | ELIMINADO; se reutiliza categoría nativa existente | no añadir enum/migración por una etiqueta |
| `db/repository.py`, `worktree_manager.py` y conteo de tablas | RETAIN-WITH-REASON, deuda fuera de #196 | requieren auditoría independiente, no son necesarios para esta reparación |

Cada retiro se acepta solo si sus consumidores y regresiones quedan cubiertos; no se elimina historia durable.
