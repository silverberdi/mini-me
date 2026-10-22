## Why

mini me conserva un registro de proyectos y una ruta de onboarding heredada, pero no ofrece una configuración completa, coherente ni configurable por proyecto; tampoco puede preparar un proyecto GREENFIELD desde contexto documental real. F2 hace que el alta sea útil de extremo a extremo sin convertir mini me en fuente local de tickets ni adelantar el ciclo autónomo de F3.

## What Changes

- Unificar alta, consulta, edición y ciclo de vida de proyectos en una sola semántica API/CLI; exigir tipo, repositorio, rama y configuraciones válidas, y exigir ZIP válido antes de persistir un GREENFIELD.
- Separar catálogos de capacidades/metadatos de proveedores y agentes de las conexiones, referencias a credenciales y perfiles que pertenecen a cada proyecto. Implementar GitHub Issues y GitHub Git/PR como responsabilidades separadas; otros proveedores no serán seleccionables ni simulados.
- Configurar los cuatro roles por proyecto con capacidades, modelos, esfuerzos, workflows y skills descubiertos/verificados; mantener independencia del revisor, gasto autorizado y límites finitos. F2 usará el agente de pensamiento real durante el onboarding.
- Preparar un GREENFIELD en workspace administrado y rama aislada: instalar/verificar OpenSpec oficial y las integraciones nativas requeridas, organizar fielmente el ZIP con el agente de pensamiento, enlazar contexto canónico y publicar el primer PR. El proyecto solo queda preparado después de confirmar el merge.
- Permitir añadir ZIP de contexto de forma incremental mediante rama y PR nuevos; el contexto efectivo no cambia antes del merge.
- Migrar PostgreSQL con Alembic de forma conservadora, conservar identidad, bindings, seguridad y evidencia operativa necesaria, retirar campos/rutas de backlog local y de admisión sin vigencia y probar datos existentes, backup y reversibilidad.
- Reconciliar las rutas duplicadas de alta y los consumidores de los campos reemplazados; conservar autenticación, Git/GitHub, aislamiento, worktrees, presupuesto, secretos y despacho/evidencia nativos reutilizables.

## Capabilities

### New Capabilities
- `project-provider-configuration`: catálogos de proveedores sin conexiones, configuración GitHub por proyecto y separación tickets/Git/PR.
- `project-agent-configuration`: catálogo verificable de agentes, capacidades y perfiles por rol con workflows nativos.
- `greenfield-project-bootstrap`: creación GREENFIELD segura desde ZIP hasta primer PR y preparación solo tras merge.
- `project-context-ingestion`: recepción, extracción segura y organización fiel del contexto por agente real.
- `incremental-project-context`: ampliaciones de contexto versionadas en ramas/PR separadas.

### Modified Capabilities
- `project-registry`: reemplazar el registro heredado por tipo explícito, configuración completa, ciclo de vida veraz y reglas para GREENFIELD/BROWNFIELD.

## Impact

Principalmente `src/minime/services/project_service.py`, `project_onboarding_service.py`, modelos/contratos/repositorios PostgreSQL, migraciones Alembic, rutas de proyectos en FastAPI, CLI, adaptador GitHub, resolución de perfiles de `config.py`, adaptadores de proveedores/OpenSpec, guardas de workspace e identidad, servicio de presupuesto y pruebas de proyectos, GitHub, agentes, seguridad y persistencia. No incluye UI nueva, ejecución de tickets, scheduler, adaptación BROWNFIELD, ADO, skills nuevas ni despliegue productivo.
