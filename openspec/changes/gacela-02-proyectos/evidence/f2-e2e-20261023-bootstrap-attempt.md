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
