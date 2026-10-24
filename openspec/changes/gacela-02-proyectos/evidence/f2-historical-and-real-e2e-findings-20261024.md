# F2 — resultados de continuidad histórica y gate E2E

Fecha: 2026-10-24. Esta evidencia no ejecutó agentes, no hizo merges, no
escribió PostgreSQL operativo y no activó scheduler.

## 7.1b — inspección read-only de producción

La conexión al PostgreSQL operativo se abrió con `SET TRANSACTION READ ONLY`.
El resultado observado fue:

- Alembic: `r02_contract_review_budget_identity`; las columnas F2
  (`project_type`, `provider_connections`, `agent_profiles`,
  `execution_policy`, `onboarding_checkpoint`) aún no existen.
- `mini-me`: repositorio `silverberdi/mini-me`, rama `main`, estado legacy
  `ACTIVE/READY_FOR_WORK`, implementer `codex`, reviewer `antigravity`.
- `mini-me-fixture`: repositorio
  `silverberdi/mini-me-r01-e2e-20261014`, rama `main`, estado legacy
  `ACTIVE/READY_FOR_WORK`, implementer `codex`, reviewer `antigravity`.
- No se inventó ningún perfil, conexión, credencial ni estado `PREPARED`.
  Ambas filas requieren migración/configuración explícita para ser elegibles
  por F3.
- Conteos observados: `project_bindings` 33 para `mini-me` y 1 para el
  fixture; un managed binding por proyecto. Los bindings permanecen separados.
  La base operativa no fue modificada.
- Workspaces administrados observados en `/opt/minime/repos/mini-me` y
  `/opt/minime/repos/mini-me-r01-e2e-20261014`, ambos en `main` y dirty; no se
  limpiaron ni se reescribieron. Sus remotos coinciden con las identidades
  anteriores. El repositorio principal conserva OpenSpec/contexto histórico;
  el fixture conserva su conjunto separado de artefactos.
- La GitHub App del servicio confirmó lectura de ambas identidades y sus ramas
  `main` (`2f7ae04530a4b3d993611c29b20c850bedc87a8c` para `mini-me` y
  `6c051b87eb9a8f379e9305b62773bf486a7825f5` para el fixture). En la respuesta
  de instalación, ambos repositorios reportan `push=false`; no existe permiso
  efectivo para publicar ramas/PR desde mini me. No se intentó mutar ninguno.

## Continuidad en PostgreSQL desechable

Se creó el contenedor desechable `minime-f2-historical-pg-20261024` sin copiar
secretos operativos. Se insertó una representación sintética de las dos filas
legacy y sus 33/1 bindings, con un managed binding por proyecto. La secuencia
ejecutada fue:

```text
r02_contract_review_budget_identity
  -> f2_project_configuration
  -> f2_retire_project_admission_columns
  -> f2_retire_project_legacy_context
  -> downgrade r02_contract_review_budget_identity
  -> re-upgrade f2_retire_project_legacy_context
```

También se hizo `pg_dump`/restore en `minime_history_restore`. Después de
upgrade, re-upgrade y restore se observaron `projects=2`, `bindings=34` y
`managed=2`; ambos proyectos quedaron `BROWNFIELD/CONFIGURED`, con el motivo
conservador `Legacy readiness requires F2 identity and capability evidence`,
sin perfiles ni conexiones F2 inventados. No se creó un proyecto duplicado ni
se forzó ZIP/PR histórico.

## 4.4/8.4 — checkpoint Greenfield sin replay

El proyecto `f2-e2e-gacela-20261023e` sigue `BLOCKED`, con el ZIP SHA-256
`3eed0aacf1f3cbe4361805b914d4fe659dbca69266f55279cdc55c10eef12e81`.
El checkpoint conserva:

- intento Codex `SUCCEEDED`, `OBSERVED`, exit `0`, duración `60433 ms`;
- uso observado: `163590` input, `146048` cached input, `3348` output;
- concesión `6373419891` marcada `used=true`;
- `bootstrap_recovery.safe_to_resume=true`, pero sin candidato recuperable.

El workspace solo conserva `main` en
`fa4eb55699b2169e5ff88059504872f17df617ce` y una rama local en el mismo SHA;
no hay branch remoto, PR ni worktree de candidato. No se repitió inferencia ni
se reutilizó la concesión incremental.

## Estado de aceptación

La evidencia local determinista publicada en `8ed15fe` y la regresión
`745 passed, 13 skipped` siguen vigentes. Las tareas 4.4, 7.1b, 8.4 y 8.5 no
se marcan completas: falta un candidato/PR Greenfield real y los dos históricos
carecen de configuración F2 verificable; además, la GitHub App del servicio no
tiene `push` efectivo en los repos históricos.

Intervenciones concretas pendientes:

1. Una nueva autorización explícita de consumo para un bootstrap Greenfield no
   puede inferirse de la concesión incremental consumida/reservada.
2. Para 7.1b, una intervención administrativa debe configurar y verificar, sin
   defaults inventados, los perfiles/conexiones F2 de cada histórico y conceder
   a la GitHub App del servicio `contents=write` y `pull_requests=write` donde
   F3/F5 lo requieran. El fixture debe conservar su aislamiento.
