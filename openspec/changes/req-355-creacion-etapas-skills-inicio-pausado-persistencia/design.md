## Context

Ver `proposal.md` y `specs/project-registry/spec.md`. Actualmente, la creación de proyectos se limita a un insert ciego en la tabla `projects`, sin verificar conectividad con GitHub, sin inicializar `/opt/minime/repos/<slug>` y sin aprovisionar las skills necesarias para que Codex y Antigravity operen. Además, el frontend no guarda la preferencia de proyecto en `localStorage`, causando reseteos constantes hacia `mini-me`.

## Goals / Non-Goals

**Goals:**
- Validación preflight de conectividad y grants de GitHub App (`issues`, `contents`, `pull_requests`) antes de persistir cualquier registro.
- Aprovisionamiento atómico del clon gestionado base en el servidor (`/opt/minime/repos/<slug>`) y su `ProjectManagedRepositoryBinding`.
- Aprovisionamiento automático en el repositorio de las skills y workflows canónicos de mini me y OpenSpec (`minime-request-normalizer`, `minime-pr-preparer`, `openspec-*`, `opsx-*`).
- Asignación obligatoria de estado inicial `PAUSED` con `effective_pause: true`.
- Stepper visible en la interfaz web para mostrar el progreso de las 4 etapas durante el registro.
- Persistencia estricta de `selectedProjectId` en `localStorage` para respetar la selección del operador sin reseteos automáticos.

**Non-Goals:**
- No alterar las reglas de selección de tickets FIFO del scheduler.
- No modificar el flujo de ejecución de los agentes ni reimplementar OpenSpec.
- No auto-asignar repositorios en GitHub sin pasar por los permisos de la GitHub App.

## Decisions

### 1. Pipeline de registro de 4 etapas secuenciales
Se implementa un pipeline secuencial en el registro de proyectos:
- **Etapa 1: Conexión GitHub**: Verifica que el repositorio sea accesible y observable por la instalación de la GitHub App (`GitHubAdapter.validate_repository_access(repo)`). Falla closed de inmediato si no hay acceso.
- **Etapa 2: Clon & Binding**: Clona el repositorio en `/opt/minime/repos/<project_id>`, genera `.minime-managed-project.json` y persiste el `ProjectManagedRepositoryBinding` con `is_valid = True`.
- **Etapa 3: Aprovisionamiento de Skills**: Copia o inicializa las skills canónicas indispensables (`.agents/skills/minime-request-normalizer`, `.agents/skills/openspec-*`, `.agent/workflows/opsx-*`) en el repositorio gestionado.
- **Etapa 4: Preflight de Verificación**: Valida que los archivos de workflow requeridos por los modelos configurados existan y sean legibles.

*Alternativa descartada:* Deferir el clon hasta que el scheduler tome el primer ticket. Causa fallos opacos y bloqueos silenciosos en producción.

### 2. Estado inicial inmutable en `PAUSED`
Todo proyecto recién creado se inicializa con `status = 'PAUSED'` y `execution_policy.effective_pause = true`.

*Alternativa descartada:* Nacer activo (`ACTIVE`). Provoca que el scheduler compita inmediatamente con el proyecto actualmente en desarrollo sin autorización expresa del operador.

### 3. Persistencia de selección de proyecto en `localStorage`
En `RefreshService`, la señal `selectedProjectId` lee su valor inicial desde `localStorage.getItem('minime_selected_project_id')` y cada invocación a `setSelectedProject(id)` lo escribe en `localStorage`. El `computed activeProject` respeta incondicionalmente esta selección si el proyecto existe en la lista.

*Alternativa descartada:* Mantener solo en memoria del componente. Provoca reseteos hacia el primer proyecto activo (`mini-me`) con cualquier evento o recarga.

## Risks / Trade-offs

- [Tiempo de clon remoto en la creación] → Se optimiza usando el mirror existente o clon superficial en base branch (`--branch <base_branch> --depth 50` o clon estándar ligero).
- [Falta de permisos en GitHub App] → Se detecta en la Etapa 1 con error explícito que instruye al usuario a seleccionar *"All repositories"* o añadir el repositorio en la configuración de GitHub.
