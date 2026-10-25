# F4 — Resolución de revisión del PR correctivo #183

- PR: https://github.com/silverberdi/mini-me/pull/183
- Head publicado: `52226a56a54f0bb122793619ea50029ab8b3e68d`.
- Base: `741eff678c71e673c1abeb6e5cdbdc88993b36f5`.
- Estado: abierto, no fusionado.

## P1 — contrato de normalización

Las dos copias de `minime-request-normalizer` exigen ahora exactamente `normalized_body`, `criteria` y `semantic_message`. La prueba `test_normalizer_skills_match_coordinator_schema` contrasta ambas skills con el esquema requerido por `NativeOrchestrationCoordinator`.

## P1 — diagnóstico durable

El Run original `8bdf3c9a-36c5-4a38-bf18-96fe71a2326c` no conserva exit code, timeout ni salida estructurada del despacho anterior; esos datos siguen `UNKNOWN` y no se inventa una causa. La frontera corregida persiste un registro `IN_PROGRESS` antes del despacho y actualiza después exit code, timeout, flags de salida, duración, diagnóstico sanitizado y uso solo cuando aparece un evento Codex `turn.completed` válido. Las reentradas sobre un intento despachado se bloquean sin reintento automático.

La regresión `test_failed_normalization_persists_diagnostic_and_blocks_reentry` demuestra fallo durable, datos desconocidos explícitos y exactamente cero llamadas duplicadas. No se ejecutaron agentes reales durante la corrección.

## Validación

- Pruebas focalizadas: `30 passed`.
- Ruff del alcance afectado: `PASS`.
- OpenSpec strict: `PASS`.
- `git diff --check`: `PASS`.

El E2E #5 permanece bloqueado y el PR correctivo requiere merge humano antes de evaluar una nueva autorización; no se ejecutaron Verify/Sync/Archive ni se modificó el Issue #172.
