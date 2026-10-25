# F4 — corrección del canal de respuesta estructurada

## Diagnóstico

El intento `c73ee7a1-6e4d-4cec-9f6f-ea43db6fd21b` terminó con exit code 0, pero el runner aplicó el límite de diagnósticos de 4.000 caracteres al archivo `--output-last-message`. La respuesta no pudo verificarse y el Run quedó bloqueado sin efectos remotos.

## Corrección

- `CliAgentRunner` mantiene separados los diagnósticos truncables y el último mensaje estructurado.
- El JSON estructurado se conserva completo hasta 1 MiB; ausencia, tamaño excesivo o respuesta inválida siguen siendo fail-closed.
- El coordinador valida exactamente `normalized_body`, `criteria` y `semantic_message`.
- La respuesta validada se persiste antes de publicar GitHub y puede reconciliarse sin redespacho.
- El estado durable distingue proceso terminado, respuesta validada y publicación confirmada.

## Verificación

En Ubuntu, sobre el checkout del candidato:

- 33 pruebas focalizadas: PASS.
- Diagnósticos extensos y JSON válido superior a 4.000 caracteres: PASS.
- Respuesta superior al límite seguro: bloqueada correctamente.
- Reconciliación desde checkpoint validado sin invocación duplicada: PASS.
- Ruff afectado: PASS.
- OpenSpec strict: PASS.
- `git diff --check`: PASS.

No se ejecutaron agentes reales, E2E, Verify, Sync ni Archive.
