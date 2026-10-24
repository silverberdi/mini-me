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
  de instalación, ambos repositorios reportan `push=false`; esos campos del
  objeto repositorio NO prueban qué grants `contents`/`pull_requests` posee
  el token GitHub App. La escritura sigue SIN PROBAR. No se intentó mutar ninguno.

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
carecen de configuración F2 verificable. El gate de publicación GitHub sigue
SIN PROBAR: la evidencia no muestra los grants del token de instalación.

Intervenciones concretas pendientes:

1. Una nueva autorización explícita de consumo para un bootstrap Greenfield no
   puede inferirse de la concesión incremental consumida/reservada.
2. Para 7.1b, una intervención administrativa debe configurar y verificar, sin
   defaults inventados, los perfiles/conexiones F2 de cada histórico. Verificar los
   grants `contents`/`pull_requests` del token de instalación exacto antes
   de solicitar cambios de permisos. El fixture debe conservar su aislamiento.

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
  preflight NO registró los grants `contents`/`pull_requests` del objeto
  `permissions` devuelto por `POST /app/installations/{id}/access_tokens`.
  No hay evidencia de falta de escritura: los flags `push`/`pull` del objeto
  repositorio no sustituyen los permisos efectivos del token.
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

Resultado: `BLOCKED` para aceptación 7.1b/8.4 por runtime obsoleto,
configuración histórica ausente y E2E real no ejecutado. Gate GitHub 2.5:
`PERMISSIONS_UNVERIFIED`, no `WRITE_DENIED`. El proyecto E2E permanece sin
branches adicionales ni PR y el intento consumido permanece `BLOCKED`; no se
repitió inferencia ni se consumió la concesión incremental.

## Continuación autenticada de 7.1b (2026-10-24)

La verificación se repitió con el runtime F2 aislado y con una copia auténtica
de los registros históricos. La base operativa solo se leyó; no se ejecutó
DDL, DML, migración ni escritura en ninguno de los workspaces productivos.

La copia desechable `minime_history_authentic` conserva, después de alcanzar
`f2_retire_project_legacy_context`, los siguientes conteos observados:

```text
projects                                  2
project_bindings                          34
project_managed_repository_bindings        2
events                                39513
jobs                                      79
auth_sessions                             16
auth_audit_events                         11
authorized_operators                       2
```

Las filas siguen siendo exactamente `mini-me` → `silverberdi/mini-me` y
`mini-me-fixture` → `silverberdi/mini-me-r01-e2e-20261014`, ambas en `main`,
`BROWNFIELD/CONFIGURED`, con el checkpoint que conserva el `READY_FOR_WORK`
histórico y su razón. No se duplicaron proyectos, bindings, worktrees ni
managed bindings. Los perfiles, conexiones y credenciales no se rellenaron
con defaults inventados.

Se restauró el dump auténtico en la segunda base desechable
`minime_history_authentic_restore_20261024` y se ejecutó la secuencia
`upgrade head → downgrade r02_contract_review_budget_identity → upgrade
head`. La base terminó en `f2_retire_project_legacy_context` con los mismos
2/34/2 y las dos identidades intactas. La dependencia global de presupuesto
`openrouter_pricing_snapshots` se incorporó desde producción mediante lectura
aislada (3 filas, sin mostrar valores sensibles), por lo que también se
restableció la FK de `budget_reservations` en la copia. La reserva histórica y
las filas de autenticación permanecieron conservadas.

El catálogo F2 del runtime actualizado observó:

- Codex: `OBSERVED_READ_ONLY`, `gpt-5.6-luna` con `medium`, roles de
  implementación/revisión, OpenSpec oficial y workflows nativos observables.
- Antigravity: `UNAVAILABLE`, sin modelo observable, sin workflow nativo
  verificable en este entorno.

La selección histórica autorizada exige Antigravity como revisor independiente
con `gemini-3.8-flash-medium`; por el contrato de validación fail-closed no es
válido persistir esa selección como si estuviera disponible ni conferir
`PREPARED` desde el sentinel legacy. Por ello 7.1b permanece correctamente
pendiente: la preservación y migración están demostradas, pero la elegibilidad
histórica completa requiere una capacidad Antigravity observable y su
configuración real. El fixture sigue aislado y no hereda credenciales del
proyecto principal.

## Clasificación de aceptación 8.5

La E2E Greenfield/incremental y su evidencia de merges ya están completas en
`f2-disposable-greenfield-merge-20261024.md`; no se repitieron agentes ni
merges. La regresión focalizada F2 de 98 pruebas, Ruff afectado, OpenSpec
strict y `git diff --check` continúan pasando. La regresión completa del
runtime actualizado terminó con 744 pasadas, 10 omitidas y 8 fallos. La
clasificación reproducida es:

1. El test de fallback de `MINIME_RUNTIME_ROOT` conserva el contrato antiguo
   `.minime`; F2 usa correctamente `/opt/minime/runtime` y fail-closed.
2–3. Dos tests de instalación/catálogo esperan 12 integraciones, pero OpenSpec
   oficial 1.13.1 expone 6 workflows nativos actuales; F2 no inventa los seis
   restantes.
4–5. Dos tests de limpieza de grupos de procesos no convergen en este host
   Ubuntu/Python 3.14 durante watchdog/cancelación; no fallan los tests de
   persistencia, recuperación ni confinamiento F2.
6. El fixture remoto contenía dos AppleDouble `._*.js`; fueron retirados solo
   del runtime desechable y `tests/test_pwa_assets.py` pasó 2/2. El checkout
   publicado no contiene esos archivos.
7. Un test de perfiles F1 exige DeepSeek Direct para code review; no es una
   capacidad ni una selección del contrato F2.
8. El preflight Antigravity falla porque la CLI no expone catálogo de modelos;
   coincide con el estado F2 `UNAVAILABLE` y debe seguir bloqueando fail-closed.

No se ocultan estos fallos como PASS. No queda un defecto de preservación
atribuible a la migración F2 en la copia auténtica.

8.5 no se marca completa porque su matriz exige reconciliar también la
elegibilidad histórica con capacidades realmente observadas y cerrar el gate
de revisión independiente. La única dependencia externa concreta es hacer
observable/configurar Antigravity con el modelo y workflow oficial autorizados,
o tomar una decisión explícita del propietario sobre una alternativa que el
catálogo actual verifique; no se inventa una selección ni se modifica
producción para sortearla.

Corrección de interpretación: el propietario confirmó que la GitHub App ya
estaba configurada con `Contents: Read and write` y `Pull requests: Read and
write`. NO solicitar reinstalación ni nuevos cambios de permisos sobre la
base de `permissions.push=false`. Verificar desde el runtime F2 aislado
con identidad exacta los grants del token de instalación (sin revelar secretos).
Si son correctos, probar la publicación solo con una operación segura y
autorizada en el repositorio E2E, nunca con una inferencia pagada. El runtime
productivo continúa fuera de alcance hasta rollout autorizado y faltan los
perfiles/conexiones históricos explícitos. Ninguna autorización de gasto se
reutiliza ni se solicita implícitamente.

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
8.5 siguen sin evidencia suficiente. RETIRADA la instrucción de cambiar permisos
o reinstalar la App `154974444`: el propietario confirma que ya tiene
`Contents: Read and write` y `Pull requests: Read and write`. El único gate
técnico pendiente de GitHub es consultar, usando el token de la instalación
actual, el mapa `permissions` emitido por GitHub al crear ese token; no
usar `permissions.push/pull` de `GET /installation/repositories` como sustituto.
Si el token confirma permisos, continuar con prueba segura de publicación
autorizada en el E2E desechable. La migración productiva y los perfiles/conexiones
históricos requieren decisiones independientes. No invocar un agente de pago
hasta que la publicación esté probada y exista autorización nueva.

## Publicación controlada con la GitHub App (2026-10-24)

Se verificó directamente el intercambio del token de instalación `154974444`
con las credenciales del servicio, sin revelar el token ni claves. Los grants
observados fueron `contents=write`, `pull_requests=write`, `issues=write`,
`metadata=read` y `checks=read`. El objeto `permissions.push` del repositorio
no se utilizó como criterio de autorización.

Sin ejecutar Codex, Antigravity ni ningún modelo, la App publicó en el único
repositorio desechable autorizado:

- repositorio: `silverberdi/mini-me-f2-e2e-20261023`;
- base `main`: `fa4eb55699b2169e5ff88059504872f17df617ce`;
- rama: `minime/f2-app-permission-probe-20261024`;
- commit publicado: `32efe90b27d5e8c12a54a77b0808183e01001cd0`;
- PR Draft: https://github.com/silverberdi/mini-me-f2-e2e-20261023/pull/1;
- base/head verificados: `main` / `minime/f2-app-permission-probe-20261024`;
- `main` permaneció intacta en el SHA base.

El commit contiene únicamente `f2-e2e-permission-probe.md`. La rama, el
commit, el archivo y el PR fueron reconsultados mediante el mismo token de
instalación. No se fusionó ni se modificó ningún repositorio histórico.

Regresión adicional: `tests/test_github_ticket_contract.py` terminó con
`11 passed`; Ruff afectado, OpenSpec strict y `git diff --check` PASS. Esto
demuestra publicación real y elimina el bloqueo de permisos, pero no completa
4.4 ni 8.4: aún no existe una invocación de pensamiento autorizada en esta
sesión, ni el primer/segundo PR documental con merges humanos.

## Greenfield real: invocación y PR (2026-10-24)

La autorización explícita `operator-instruction-f2-greenfield-20261024-1`
permitió exactamente una invocación nueva. La primera ejecución del coordinador
se detuvo antes del agente porque el runtime cargaba la configuración antigua y
el scope guard rechazaba los dos scaffolds `.gitkeep` oficiales de OpenSpec;
no hubo consumo. Se corrigió la allowlist y se verificó con `29 passed`.

Después se ejecutó una sola invocación real, sin fallback ni reintento:

- proyecto: `f2-e2e-gacela-20261023e`;
- repositorio: `silverberdi/mini-me-f2-e2e-20261023`;
- ZIP: `3eed0aacf1f3cbe4361805b914d4fe659dbca69266f55279cdc55c10eef12e81`;
- modelo/esfuerzo: `gpt-5.6-luna` / `medium`;
- aislamiento: Bubblewrap, worktree del proyecto y runtime separado;
- resultado Codex: `exit_code=0`, `timed_out=false`, duración `71213 ms`;
- uso observado: `222562` input, `200960` cached input, `6535` output.

Codex produjo el catálogo documental, `context/INDEX.md`, procedencia e
original bajo `context/incoming/<sha>/`. La validación de candidato, scope y
OpenSpec oficial pasó. El commit posterior falló inicialmente por ausencia de
identidad Git en el worktree; el candidato quedó preservado en cuarentena y se
recuperó sin nueva inferencia configurando una identidad técnica no sensible.

Resultado publicado mediante la GitHub App:

- base `main`: `fa4eb55699b2169e5ff88059504872f17df617ce`;
- rama: `minime/bootstrap/f2-e2e-gacela-20261023e-3eed0aacf1f3`;
- commit: `16dd7f3ad84800c242d57790aea895881734edc9`;
- PR Greenfield Draft: https://github.com/silverberdi/mini-me-f2-e2e-20261023/pull/2;
- estado persistido: `PR_PENDING`;
- `main` permaneció intacta.

La tarea 4.4 queda completa con esta evidencia. La tarea 8.4 permanece
pendiente hasta observar el merge humano del PR #2 y ejecutar, con autorización
independiente, el contexto incremental y su segundo PR. No se fusionó ningún
PR ni se inició F3.
