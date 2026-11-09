## Why

Actualmente, el registro de proyectos en mini me es un guardado plano que no valida permisos remotos ni aprovisiona las capacidades mínimas necesarias para ejecutar trabajo. Al registrar un proyecto, el sistema devuelve `201 Created` sin comprobar el acceso de la GitHub App, sin crear el clon gestionado base en `/opt/minime/repos/<slug>`, sin registrar su `ProjectManagedRepositoryBinding` y sin verificar que el repositorio contenga los workflows y skills indispensables (`.agents/skills/minime-request-normalizer`, `openspec-*`, `.agent/workflows/opsx-*`). Cuando el scheduler toma el primer ticket, falla inmediatamente de forma opaca (`Project has no verified repository binding` o `workflow 'normalize' is missing`). Además, el proyecto nace activo, pudiendo interferir con otros proyectos en ejecución, y en el frontend la selección de proyecto se resetea a `mini-me` periódicamente por falta de persistencia en `localStorage`.

Es necesario un flujo de creación guiado por etapas atómicas, aprovisionamiento automático de repositorio y skills, estado inicial estrictamente pausado y persistencia permanente de la selección del operador.

## What Changes

- **Validación remota previa de permisos GitHub (Etapa 1)**: `POST /api/v1/projects` (y el modal de creación) valida contra GitHub que la instalación de la GitHub App tiene acceso de lectura/escritura (`issues`, `contents`, `pull_requests`) al repositorio especificado antes de persistir cualquier registro. Si no tiene acceso, reporta el error directamente en el formulario con instrucción clara de autorización.
- **Aprovisionamiento atómico de repositorio gestionado (Etapa 2)**: Inicializa de inmediato el clon base en `/opt/minime/repos/<slug>`, genera su archivo marcador de propiedad `.minime-managed-project.json` y registra el `ProjectManagedRepositoryBinding` con `is_valid = True`.
- **Aprovisionamiento de Skills y Workflows canónicos (Etapa 3)**: Aprovisiona en el repositorio local las skills y workflows oficiales requeridos por los roles de agentes asignados (`minime-request-normalizer`, `minime-pr-preparer`, `openspec-*`, `.agent/workflows/opsx-*`).
- **Preflight de Readiness y Creación Atómica (Etapa 4)**: Comprueba que todos los workflows y skills asignados sean archivos regulares y válidos antes de dar por completada la creación. Si alguna etapa falla, se revierte limpiamente sin dejar estados huérfanos.
- **Estado Inicial Estrictamente PAUSED**: Todo proyecto nuevo se persiste obligatoriamente con `status = 'PAUSED'` y `effective_pause = true`, requiriendo activación manual y deliberada del operador sin afectar la ejecución de otros proyectos en curso.
- **Avance de etapas visible en UI**: El modal de creación de proyectos muestra un avance paso a paso (stepper de 4 etapas: Conexión GitHub → Clon & Binding → Skills de Agentes → Verificación Final) que informa al operador en tiempo real.
- **Persistencia de Selección de Proyecto en UI**: `RefreshService` persiste `selectedProjectId` en `localStorage` de modo que la selección manual del operador sea permanente y nunca se resetee automáticamente a `mini-me` ante eventos SSE, recargas o navegación entre vistas. Se erradican temporizadores que fuercen refrescos periódicos indeseados.

## Capabilities

### Modified Capabilities
- `project-registry`: Exige que el registro de proyectos Brownfield valide el acceso de GitHub App, aprovisione el repositorio gestionado raíz con su binding y capacidades de agentes requeridas, y asigne por defecto el estado `PAUSED`.
- `pwa-app-shell-and-queue`: Exige la persistencia duradera del proyecto seleccionado en `localStorage` y la visualización del progreso por etapas en la creación de proyectos sin recargas cíclicas ni reseteos arbitrarios.

## Impact

- **Backend**:
  - `src/minime/api/app.py`: Endpoint `POST /api/v1/projects` ejecuta el pipeline de validación y aprovisionamiento de 4 etapas antes de persistir y devuelve el estado `PAUSED`.
  - `src/minime/services/project_service.py` y `src/minime/services/project_onboarding_service.py`: Integración de validación de grants de GitHub App, clonado/binding atómico e instalación de skills requeridas.
- **Frontend**:
  - `frontend/src/app/core/refresh.service.ts`: Persistencia de `selectedProjectId` en `localStorage` y preservación incondicional de la selección del operador.
  - `frontend/src/app/features/proyectos/proyectos.component.ts` y template: Stepper de 4 etapas con progreso visible durante la creación del proyecto.
- **Pruebas**:
  - Pruebas unitarias de backend para validación de permisos, binding automático, provisión de skills y estado `PAUSED`.
  - Pruebas frontend unitarias y Playwright E2E para el stepper de creación y la persistencia en `localStorage`.
