# F4 — Recuperación y publicación de normalización

Fecha: 2026-10-25

## Resultado

`F4_PUBLICATION_CONFIRMED`. No se ejecutó ningún modelo durante la recuperación.

- Run: `fdca564f-7000-4a2f-a243-9a4bc9938750`
- Attempt: `359f3663-ea54-4bbf-b581-de435165d635`
- Issue: https://github.com/silverberdi/mini-me-f2-e2e-20261023/issues/5
- Autorización operativa: comentario `6401285101` del Issue #172.
- Checkpoint: `validated_normalization_response`.
- Estado durable final: `publish_status=CONFIRMED`.
- Hash del `normalized_body` registrado en el checkpoint: `527ef6bca2e3c8d8479f46e68b5abc24d8d11598f191389310f9c4cc64f6a616`.

## Verificación remota

La publicación se realizó mediante un único `PATCH` documentado de actualización de Issue, sin `If-Match` no documentado. Se ejecutó bajo exclusión del fixture, con lectura fresca del cuerpo y comparación previa del contenido original.

- Resultado del PATCH: `HTTP 200`.
- `reason_code`: `EXECUTION_SUCCESS`.
- GET independiente posterior: el cuerpo remoto coincide íntegramente con el contenido Gherkin validado del checkpoint.
- Cuerpo remoto observado: `# language: es`, una `Característica`, tres `Escenarios` y pasos `Dado/Cuando/Entonces` con los criterios C1, C2 y C3.
- Comentario de preservación literal: ID `6400977375`, marcador del Run presente una vez.
- Comentario semántico en español: ID `6400977558`, marcador del Run presente una vez.
- No se crearon comentarios duplicados, Runs ni Attempts.
- El cuerpo original no se reescribió en el comentario de preservación; el Issue quedó con el Gherkin validado.

La evidencia remota actual del Issue contiene el cuerpo Gherkin y ambos comentarios asociados al mismo Run. La recuperación no volvió a invocar `agent_runner.run()` y no inició Explore.

## Diagnóstico de recuperación

La ruta previa de alto nivel conservaba una precondición de versión/ETag que no correspondía al contrato documentado del endpoint de actualización de Issue. La reconciliación controlada releyó el cuerpo, aplicó el PATCH único sin esa precondición no soportada y confirmó el resultado mediante GET independiente. No se atribuyó consumo desconocido a cero ni se alteró el checkpoint VALIDATED.
