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

## Correcciones verificadas en esta continuación

- `NativeOrchestrationCoordinator` en las rutas CLI/API solicita a `minime-pr-preparer` contenido semántico JSON para PR1 y PR2; la publicación queda bloqueada ante skill ausente, salida incompleta, diagnóstico, timeout o respuesta no estructurada.
- La preparación ya no usa el texto de éxito por defecto para pruebas ausentes: PR1 exige evidencia de tests persistida con resultado verificable.
- El manifest Greenfield selecciona recursos por proveedor y perfil, excluye fallback no autorizado y registra las rutas seleccionadas; no copia indiscriminadamente ambos árboles de agente.
- La readiness F5 registra perfiles, OpenSpec, Worktree, confinamiento y binding GitHub, sin ejecutar F5 ni tocar Brownfield.
- S01 entrega al agente el cuerpo, comentarios y adjuntos declarados del Issue; persiste un hash del contexto fuente junto con el checkpoint para reanudación.

## Preflight E2E sin inferencia

- Codex CLI observado: `0.161.0`; esta sesión interactiva informa autenticación ChatGPT, no constituye identidad de servicio F2.
- AGY observado: `1.4.7`; `agy models` mostró `gemini-3.8-flash-medium`.
- Configuración estática prevista: Codex `gpt-5.6-luna`, medium; Antigravity `gemini-3.8-flash-medium`, medium. La disponibilidad efectiva de Codex bajo la identidad de servicio no pudo verificarse desde esta sesión.
- Identidad GitHub App, instalación, PostgreSQL desechable y workspace administrado no son observables localmente: las variables de servicio `MINIME_GITHUB_APP_ID`, `MINIME_GITHUB_INSTALLATION_ID`, `MINIME_GITHUB_PRIVATE_KEY_PATH` y `MINIME_DATABASE_URL` están ausentes en esta sesión. No se usó la sesión `gh` del operador para suplirlas.
- Scheduler: `DISABLED`; fallback de pago: desactivado; OpenRouter: desactivado con presupuesto cero.
- Consumo real: `0` invocaciones F4 en esta continuación. E2E no ejecutado.
- Operación preparada: un único recorrido Greenfield controlado, sin reintentos ni fallback, con normalización, una ejecución real del flujo F3 y PRs gobernados. El número exacto de llamadas y el límite monetario deben provenir del presupuesto/contador del servicio; no se inventan desde el checkout local.

## Pendiente de autorización/evidencia externa

No se ejecutó una inferencia real durante esta validación. Quedan pendientes 5.4, 6.2, 6.4, 6.5 y 6.6 hasta disponer de identidad de servicio verificable, repositorio/Issue controlados, capacidad Codex/Antigravity observada, presupuesto con techo explícito y completar el PR/merge humano, Sync/Archive y la matriz de 35 criterios con evidencias remotas. Estas tareas permanecen sin marcar.
