# MM-R08 — multi-repository-sdd-execution

**Estado:** PLANNED (no activo). **Dependencias:** MM-R01–MM-R07. **Capacidad entregada:** Demostración de autonomía en dos repositorios reales.

## Business intent: problema → resultado real
**Antes:** Las pruebas actuales y el historial de mini me no prueban suficientemente la portabilidad del pipeline nativo OpenSpec a otro repositorio con convenciones distintas.

**Después de desplegar:** mini me incorpora un segundo repositorio autorizado, descubre su contexto real, prepara/aplica/revisa con OpenSpec y entrega un PR sin mezclar rutas, políticas ni permisos de mini me.

## Requisitos por spec (se implementan en un Change OpenSpec multi-spec)
Los Sxx son mínimos normativos. En `propose`, el agente clasifica las specs por comportamiento/capacidad, formula SHALL/SHALL NOT y escenarios Given/When/Then, resuelve tradeoffs en design, y crea tasks ordenadas incluyendo pruebas reales. No iniciar `apply` sin trazar todos los requisitos contra evidencia final y revisar no-goals.

### R08-S01 — Onboarding autoritativo
SHALL verificar owner, remote, base branch, permission scopes, tools, runtime, checks, openspec config, gitignore y deployment contract sin inferir root desde Project/Issue labels.

### R08-S02 — Contexto por proyecto
SHALL respetar README, AGENTS, BUSINESS_INTENT, arquitecturas, skills/hooks/harnesses y OpenSpec config del repositorio; biblioteca compartida solo donde se permite.

### R08-S03 — Aislamiento fuerte
SHALL aislar worktrees, secretos, runtime settings, paths, estados y cuota por proyecto; no acceso cruzado a archivos de otro managed repo ni a bases ajenas.

### R08-S04 — Política por repo
SHALL seleccionar los roles de agentes y etapas permitidos por proyecto; con independencia reviewer, budget per project y concurrencia compatible con scheduler.

### R08-S05 — Pipeline replicable
SHALL obtener Issue→OpenSpec→apply→review→PR real en segundo repo y preservar el primero; no introducir condicionales `if project==mini-me\` salvo comportamiento de autodesarrollo explícito.

### R08-S06 — Conflicto de repositorios
SHALL bloquear bindings provisionales, remote alterado, ramas inesperadas, chequeos ausentes, worktree fuera de /opt/minime/repos; nunca reparar cambiando de repo silenciosamente.

### R08-S07 — Observabilidad agregada
SHALL mostrar estado por repo y conjunto con evidencias/scope rastreables a cada project_id, sin permitir que un operador actúe en repo distinto al seleccionado.

## Escenarios E2E de etapa, Change y destino
Cada E0x es contractual y debe tener setup, ejecución, verificaciones de side effects y evidencias durables. Test mock-only no satisface un escenario que atribuye una acción a un agente/servicio real; un E2E no corrido es `BLOCKED` o `NOT VERIFIED`.

### R08-E01 — Segundo repo real
Usar otro repositorio propiedad del operador autorizado, con estructura distinta, y obtener un PR real de una funcionalidad pequeña mediante OpenSpec + agente + reviewer independiente.

### R08-E02 — Primer repo sigue sano
Después de ejecutar R08-E01, repetir smoke E2E clave de mini me y demostrar que sus worktrees, settings y OpenSpec no se tocaron.

### R08-E03 — Concurrencia controlada
Admitir dos jobs de repos distintos si configuración/recursos lo permiten; bloquear concurrentes no permitidos del mismo repo.

### R08-E04 — Remote spoofing
Alterar Git remote, symlink o identidad de Issue después de onboarding; gate bloquea antes de despacho; sin escrituras fuera del root autorizado.

### R08-E05 — E2E de contexto
Insertar una regla específica del segundo repo que contradiga una convención global no esencial; el agente debe cumplirla, el guard no debe imponer la arquitectura mini me.

### R08-E06 — Deploy de segundo repo
Verificar el artefacto funcional del repo externo en su propio entorno autorizado; no usar la URL/BD de mini me.

## Paquetes de trabajo transversales a incluir dentro del mismo Change
- Onboarding gestionado con evidencia real y configuración de proyecto mínima; corregir solo gaps que bloqueen el segundo repo.
- Verificación paralela de policy/permissions y límites Git/PWA/API.
- Conservar y reutilizar adaptadores ya probados en R01–R07.

## Límites y elementos que no deben construirse
NO multitenancy comercial, marketplace, cluster de workers, remote executor distribuido, ni portabilidad infinita. No usar Content Factory como conejillo de indias si aún faltan pruebas básicas.

## Evidencia de valor y aceptación postdeploy
Dos PRs de dos repos reales, bindings, diff/candidate SHA, evidencia de agente y OpenSpec por repo, aislamiento de paths/secrets, checks, E2E funcional postdeploy en destinos respectivos.

## Release / rollback / seguridad
El segundo repo lo elige y autoriza el operador; permisos mínimos de GitHub App; ejecutar primero en entorno QA. No tocar producción externa sin política explícita. Un design.md debe registrar contrato de instalación, preflight, owners, migraciones reversibles y recuperación de side effects desconocidos. Aplicar `docs/CHANGE_DELIVERY_CONTRACT.md` (G0–G6). No declarar DONE antes de evidencias E2E reales, comportamiento postdeploy, review independiente y gate humano de merge. No activar scheduler productivo ni proveedores pagados por crear el backlog.

## Disciplina OpenSpec
Activar únicamente mediante el workflow `propose multi-repository-sdd-execution` del agente con su sintaxis real; hacer `update` en discrepancias; `apply` para implementación; `verify` y checks para aceptación; `sync/archive` al cerrar conforme a autoridad Git. **mini me coordina quién y cuándo; el agente y OpenSpec definen e implementan el cómo.**
