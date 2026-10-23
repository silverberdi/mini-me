# F2 Greenfield E2E — intento autorizado

Fecha: 2026-10-23. Este registro conserva evidencia del intento real y no marca
tareas como completas cuando el candidato no fue publicado.

- Código ejecutado en el servidor: `b6f9f8b13c4cf8f813c6f8eb20eb99f0e96a14a4`.
- ZIP auténtico: `tests/fixtures/gacela-02-proyectos/console-sorter-context.zip`;
  SHA-256 `3eed0aacf1f3cbe4361805b914d4fe659dbca69266f55279cdc55c10eef12e81`.
- Repositorio privado desechable: `silverberdi/mini-me-f2-e2e-20261023`.
- Acceso de la GitHub App: verificado mediante token de instalación; repositorio
  visible, `private=true`, rama por defecto `main`, grants efectivos de
  `contents=write`, `issues=write` y `pull_requests=write`.
- Base provisionada: `main` en SHA
  `fa4eb55699b2169e5ff88059504872f17df617ce`. La provisión fue únicamente el
  commit README inicial del repositorio desechable.
- PostgreSQL: contenedor desechable `minime-f2-e2e-pg-a8fa889`, PostgreSQL 16,
  migrado hasta `f2_retire_project_legacy_context`; no se usó la base operativa.
- Confinamiento: `MINIME_RUNTIME_ROOT` no estaba configurado; el fallback
  efectivo fue `/opt/minime/runtime`. El workspace se aisló bajo `/tmp` y no se
  solapó con el runtime.
- Preflight Codex: PASS, modelo observado `gpt-5.6-luna`, esfuerzo `medium`,
  `codex-cli 0.159.0`, invocación `codex exec` con transporte stdin y
  confinamiento PASS.
- Resultado: la invocación real terminó con código no cero antes de producir un
  candidato. No se publicó rama de bootstrap ni PR; el único branch remoto
  observable sigue siendo `main` en el SHA base.
- Seguridad de reintento: el consumo exacto no quedó observable de forma
  determinista. Por la política de no repetir consumos ambiguos, no se ejecutó
  una segunda invocación.

Las tareas 4.4, 7.1b, 8.4 y 8.5 permanecen pendientes; este documento es
evidencia de bloqueo E2E, no evidencia de aceptación.

## Validación posterior de recuperación

- La revisión publicada en `2b319b52ba2c744170e97a9a3707f74b3860c89b` fue
  verificada localmente y el cambio posterior quedó publicado en
  `ed69ce76afc9c66c7aeebc4e76e1160dd21d8141`.
- Regresión completa posterior: `729 passed, 13 skipped, 2 warnings`; Ruff de
  archivos afectados, OpenSpec strict y `git diff --check` pasan.
- La reconciliación read-only ejecutada contra PostgreSQL desechable preservó el
  proyecto `f2-e2e-gacela-20261023e` en `BLOCKED`, la identidad y el hash del
  ZIP, y añadió `bootstrap_recovery` con
  `THINKING_AGENT_ATTEMPT_EVIDENCE_UNAVAILABLE` y `safe_to_resume=false`.
- La búsqueda segura de artefactos existentes no encontró JSONL, stderr,
  registros de proceso ni un intento Codex recuperable. La fila histórica solo
  contiene el motivo genérico `GREENFIELD_BOOTSTRAP_FAILED:GreenfieldBootstrapError`.
- La recuperación no reintentó Codex, no creó ramas/PR y no modificó `main`.

## Primera invocación nueva autorizada

- La concesión del comentario `6372352972` fue validada contra el proyecto,
  ZIP, repositorio privado y `main` exactos. La reserva pre-dispatch creada por
  la versión anterior se reconcilió sin contarla como consumo de modelo.
- Invocación única ejecutada: Codex `gpt-5.6-luna`, esfuerzo `medium`,
  duración `25116 ms`, exit code `1`, timeout `false`, confinamiento/preflight
  aprobados.
- Diagnóstico JSONL/CLI conservado y redactado: `Failed to refresh token: Your
  access token could not be refreshed` y
  `workspace routing discovery unauthorized (401)` durante la reconexión.
- No apareció evento `turn.completed.usage`; consumo: `UNKNOWN`. La concesión
  quedó marcada `used=true` y no se hará reintento.
- Resultado remoto: solo `main` en
  `fa4eb55699b2169e5ff88059504872f17df617ce`, sin branch bootstrap ni PR; el
  proyecto permanece `BLOCKED` con identidad, binding y checkpoint preservados.
- Regresión posterior al cambio: `731 passed, 13 skipped, 2 warnings`; Ruff de
  archivos afectados, OpenSpec strict y diff check pasan.

## Diagnóstico de autenticación Codex sin inferencia

- Verificación realizada en el host del servicio con el usuario efectivo
  `silverman` (UID `1000`), `HOME=/home/silverman` y `CODEX_HOME` no definido.
- `AgentProcessConfinement.codex_auth_source()` resolvió exactamente
  `/home/silverman/.codex/auth.json`; el archivo es regular, propiedad del
  usuario de servicio y modo `600`. No se copiaron sus contenidos a la
  evidencia.
- `codex login status` devolvió `Logged in using ChatGPT`. Esto confirma la
  sesión almacenada, pero no contradice el `401` de renovación observado en la
  invocación: el refresh remoto rechazó el token y el CLI indicó volver a
  iniciar sesión.
- La prueba no ejecutora de `runtime_session` proyectó esa misma fuente en un
  `CODEX_HOME` privado bajo `/run/minime-agent/codex`; el archivo proyectado fue
  regular, propiedad del UID de servicio y modo `600`. La observación inicial
  no detectó rotación perdida. El proyecto E2E permanece `BLOCKED` y no se
  modificó PostgreSQL operativo, GitHub, `main` ni ningún PR.
- Se inició el mecanismo oficial `codex login --device-auth`, pero requiere
  aprobación OAuth humana en `https://auth.openai.com/codex/device`. La sesión
  interactiva se detuvo sin aceptar credenciales; no se ejecutó `codex exec`, no
  se consumió una invocación y no se publicaron códigos ni secretos.
