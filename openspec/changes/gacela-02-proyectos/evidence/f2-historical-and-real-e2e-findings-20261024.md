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

## Preflight de la instalación GitHub App y runtime (2026-10-24)

Se repitió el preflight en el host del servicio usando exclusivamente el token
de instalación generado por la App configurada; no se imprimieron tokens,
JWT, claves ni contenido de `auth.json`.

- `GET /installation/repositories` devolvió HTTP 200 y mostró exactamente
  `silverberdi/mini-me`, `silverberdi/mini-me-r01-e2e-20261014` y
  `silverberdi/mini-me-f2-e2e-20261023`. El repositorio E2E sí está
  seleccionado actualmente, pero los tres registros reportan
  `admin=false`, `maintain=false`, `pull=false`, `push=false` y
  `triage=false`.
- La misma respuesta de identidad del repositorio E2E fue HTTP 200, privado,
  rama por defecto `main`, con el mismo mapa de permisos sin escritura. La
  identidad histórica `mini-me-fixture` se verificó contra su remoto real
  `silverberdi/mini-me-r01-e2e-20261014`; no se inventó un repositorio con
  ese alias. No se hicieron mutaciones ni pruebas de escritura.
- La verificación existente solicitada por el último comentario no pudo
  ejecutarse en el runtime desplegado: el `GitHubAdapter` remoto no expone
  `verify_connection_permissions`; por tanto, el despliegue remoto está
  atrasado respecto al código F2 publicado y no se presenta como PASS. La
  inspección directa del token de instalación sí permite distinguir el caso:
  el E2E es accesible, pero sus grants efectivos no satisfacen
  `contents=write`/`pull_requests=write`.
- Bajo la identidad `silverman`, `CODEX_HOME` está ausente y Codex usa la
  fuente por defecto `/home/silverman/.codex/auth.json` (modo `600`, propietario
  `silverman`); `codex login status` respondió `Logged in using ChatGPT`.
  `codex-cli` es `0.159.0`, `agy` `1.1.25` y OpenSpec `1.13.1`. No se ejecutó
  `codex exec` ni ninguna inferencia.
- El host tiene `/usr/bin/bwrap` y `/opt/minime/runtime`; `/run/minime-agent`
  no existe y no se creó manualmente. Esto es compatible con el fallback
  fail-closed del runtime: la raíz host efectiva disponible es
  `/opt/minime/runtime`, mientras el mount interno del sandbox se crea solo
  durante una sesión confinada.
- La consulta del catálogo F2 no pudo ejecutarse en el despliegue actual:
  falta `minime.services.project_catalog_service`. Esto confirma que el host
  aún no ejecuta la revisión publicada; no se sustituyó por una configuración
  inventada. Las versiones observadas de las herramientas no constituyen
  evidencia de perfiles F2 históricos.

Resultado: `BLOCKED` para 2.5/7.1b/8.4. El proyecto E2E permanece sin
branches adicionales ni PR y el intento consumido permanece `BLOCKED`; no se
repitió inferencia ni se consumió la concesión incremental.

Acción administrativa exacta: actualizar la instalación de la GitHub App del
servicio para otorgar `contents=write` y `pull_requests=write` al repositorio
E2E y a cada repositorio histórico donde F3/F5 deba publicar, y desplegar el
commit que contiene el gate F2 antes de volver a verificar. Además, deben
configurarse explícitamente los cuatro perfiles/conexiones de cada proyecto
histórico, sin defaults. Ninguna autorización de gasto se reutiliza ni se
solicita implícitamente en esta evidencia.

## Runtime F2 aislado y límite administrativo (2026-10-24)

- Se creó un entorno virtual temporal desde el checkout del HEAD
  `0d691988e97b9efbd01c02b417b6f13d01363187`; el paquete `minime` importó
  correctamente y OpenSpec, pytest y Ruff se ejecutaron desde ese entorno.
- En PostgreSQL desechable `minime-f2-runtime-pg-20261024`, Alembic alcanzó
  `f2_retire_project_legacy_context`; la comprobación directa observó el
  esquema migrado y la tabla `projects`. No se usó la base operativa.
- Pruebas del runtime aislado: catálogo `10 passed`, coordinador Greenfield
  `18 passed`, instalación OpenSpec `10 passed`; Ruff afectado PASS, OpenSpec
  strict PASS y `git diff --check` PASS. El warning restante es únicamente
  `asyncio_mode` no reconocido por el entorno temporal, sin fallo de prueba.
- La sesión `gh` del operador está autenticada como `silverberdi`, pero no
  tiene autorización para administrar la instalación GitHub App `154974444`:
  `GET /user/installations/154974444/repositories` respondió HTTP 403
  (requiere un token autorizado a una GitHub App/PAT), y el endpoint de la
  instalación no es accesible con esa sesión. No se intentó cambiar permisos
  mediante PAT ni otra identidad.

Estado: el código y el runtime desechable están preparados; 4.4, 7.1b, 8.4 y
8.5 siguen sin evidencia suficiente. El siguiente actor debe ser el propietario
de la GitHub App en GitHub: abrir la configuración de la App cuya instalación
es `154974444`, cambiar Repository permissions a `Contents: Read and write` y
`Pull requests: Read and write`, conservar seleccionados los tres repositorios
F2, y actualizar/reinstalar la instalación. Después debe desplegarse el HEAD
F2 en el runtime del servicio y configurarse explícitamente la selección de
perfiles/conexiones históricos. Hasta entonces no puede verificarse publicación
real ni iniciarse ninguna invocación Codex.
