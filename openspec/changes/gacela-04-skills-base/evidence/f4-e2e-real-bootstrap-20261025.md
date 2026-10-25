# F4 — E2E Greenfield real

Fecha: 2026-10-25. Proyecto: `f4-e2e-gacela-20261024`.

## Autorización y límites

- Autorización: Issue #172, comentario `6393146211`.
- Candidato F4 usado: `f9e50511efaa74a0ae10830fd8e374ec38401187`.
- Un único recorrido autorizado; cero reintentos, fallback u OpenRouter.
- Límite agregado autorizado: USD 1,00. El runtime no emitió importe monetario; no se inventa un costo. El consumo observable quedó registrado abajo.
- Ejecución bajo usuario de servicio `minime` en Ubuntu, checkout aislado, PostgreSQL desechable y configuración OpenSpec XDG aislada.

## Recorrido real

- ZIP: `f4-console-sorter-context.zip`.
- SHA-256 ZIP: `3eed0aacf1f3cbe4361805b914d4fe659dbca69266f55279cdc55c10eef12e81`.
- Proyecto existente reutilizado: `f4-e2e-gacela-20261024`.
- Base limpia: `e2e/f4-clean-base-20261024` at `895c708606dae0e05be314d2f8465f8a91cc5d77`.
- La inferencia Codex previa terminó `SUCCEEDED`, `exit_code=0`, `timed_out=false`, duración `92143 ms`.
- Modelo/agente: Codex `gpt-5.6-luna`, esfuerzo `medium`.
- Consumo observable: `input_tokens=282565`, `cached_input_tokens=260224`, `output_tokens=11071`.
- La recuperación posterior no volvió a invocar ningún agente; validó y publicó el candidato preservado.

## Evidencia GitHub

- Repositorio: `silverberdi/mini-me-f2-e2e-20261023`.
- PR Greenfield: https://github.com/silverberdi/mini-me-f2-e2e-20261023/pull/4
- Rama: `minime/bootstrap/f4-e2e-gacela-20261024-3eed0aacf1f3`.
- Candidate/head SHA: `2bd7549d869fab7674776540d46cfaa72b71c400`.
- Base SHA del PR: `895c708606dae0e05be314d2f8465f8a91cc5d77`.
- `main` remoto permaneció en `4a3a5b985150dab1bc1018e781a6ca187f15ed0d`.
- Estado durable mini me: `PR_PENDING`; no se fusionó el PR.

## Controles demostrados

- Normalización y organización real de contexto producidas por Codex; fuentes originales preservadas bajo `context/incoming/<zip-sha>/`.
- Instalación oficial OpenSpec y capacidades seleccionadas para Codex/Antigravity observadas en el entorno aislado; sin sustitución de proveedor.
- Validación de alcance, procedencia, enlaces, índice, secretos, worktree y base SHA completada antes de publicar.
- Recuperación post-inferencia idempotente: se conservó el checkpoint, el intento y el worktree; no se atribuyó consumo a cero ni se repitió inferencia.
- Sin cambios en producción, Brownfield, scheduler, PostgreSQL operativo o `main`.

## Estado de aceptación

La tarea 5.4 queda demostrada. Las tareas 6.2, 6.4, 6.5 y 6.6 permanecen pendientes porque requieren merge humano del PR de implementación de prueba, Sync/Archive nativos, PR documental y la matriz final completa.
