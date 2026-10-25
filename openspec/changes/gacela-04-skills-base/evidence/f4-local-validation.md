# F4 — evidencia local de Apply

Fecha: 2026-10-24

## Validaciones ejecutadas

- Pruebas focalizadas de F4, catálogo, bootstrap, instalación OpenSpec, GitHub y ciclo F3: `57 passed`.
- Regresión completa: `810 passed, 15 skipped`.
- Ruff sobre los archivos de F4 y regresiones afectadas: `All checks passed`.
- `openspec validate gacela-04-skills-base --strict`: `PASS`.
- `git diff --check`: `PASS`.
- El único ajuste posterior a la primera regresión corrigió una fixture antigua que usaba un SHA no hexadecimal; no se relajó la validación de identidad.

## Recorrido determinista

`tests/test_f4_request_normalization.py` demuestra, sin proveedores reales, normalización, preservación literal y comentario idempotente, concurrencia optimista, manifest Greenfield idempotente/no destructivo, preparación semántica de PR y recorrido incremental de contratos. No se presenta como E2E de agente real.

## Alcance y seguridad

El diff F4 no modifica `main`, Brownfield, PostgreSQL operativo, scheduler ni workflows oficiales de OpenSpec. La instalación de capacidades queda restringida a Greenfield. El censo de rutas no demostró una ruta F4 obsoleta que pudiera retirarse sin afectar consumidores históricos o legítimos.

## Pendiente de autorización/evidencia externa

No se ejecutó una inferencia real durante esta validación. Quedan pendientes 5.4, 6.2, 6.4, 6.5 y 6.6 hasta disponer de capacidad/presupuesto autorizado y completar el PR/merge humano, Sync/Archive y la matriz de 35 criterios con evidencias remotas. Estas tareas permanecen sin marcar.
