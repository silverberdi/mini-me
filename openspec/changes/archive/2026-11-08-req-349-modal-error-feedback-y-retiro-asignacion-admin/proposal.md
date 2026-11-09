## Why

1. **Feedback de error en modales bloqueado**: En `ProyectosComponent`, cuando el operador intenta registrar o editar un proyecto y ocurre un error de validación o un rechazo del backend, el mensaje de error se renderiza en la página base detrás del telón de fondo del modal (`fixed inset-0 z-50 bg-slate-950/80`), forzando al operador a cancelar y cerrar el modal para enterarse del fallo y perdiendo los datos ya ingresados.
2. **Herencia indebida de perfiles**: Al registrar un nuevo proyecto, `buildProfile` reutiliza perfiles del proyecto activo en pantalla (`mini-me`), que pueden estar incompletos o en formato legado.
3. **Bloqueo en validación canónica del backend**: En `src/minime/api/app.py`, `_validate_live_canonical_profiles` somete obligatoriamente todos los perfiles a `CanonicalProfileResolver` consultando la tabla `provider_model_registry`. Como dicha tabla solo almacena modelos de proveedores externos (OpenCode/Ollama), la selección legítima de harnesses locales del sistema (`codex` y `antigravity`) falla sistemáticamente con `ValueError: thinker: model is absent from provider catalog`. La autoridad completa de validación de capacidades y CLIs instalados reside en `ProjectCatalogService.validate_project_profiles`.
4. **Sección desfasada y rota en administración**: En `AdminModelsComponent` (`/administracion/modelos-proveedores`) persiste una sección («Asignación por proyecto») con desplegables vacíos y sin el rol obligatorio `fallback`, duplicando de forma rota la autoridad de configuración que reside canónicamente en `Proyectos`.

## What Changes

- **Feedback de error en modales**: Mostrar alertas y mensajes de error reactivos directamente **dentro** del modal abierto de «Registrar Nuevo Proyecto» y «Editar Proyecto» (sobre los botones de acción), manteniendo visibles los datos introducidos por el operador.
- **Aislamiento y canonicidad completa de perfiles**: Garantizar que `buildProfile` construya perfiles independientes y completos (`provider_id`, `harness_id`, `model_id: targetModelId`, `effort`, `route`, `workflows`, `skills`) para los 4 roles (`thinking`, `execution`, `independent_review`, `fallback`), sin heredar perfiles de otros proyectos ni reutilizar perfiles que carezcan de proveedor y harness canónicos.
- **Reconciliación de validación en backend**: Ajustar `_validate_live_canonical_profiles` en `app.py` para que solo someta a `CanonicalProfileResolver` aquellos perfiles cuyo harness o proveedor pertenece al registro de modelos de proveedores externos (`provider_model_registry`), permitiendo que los harnesses locales (`codex` y `antigravity`) sean validados de forma autoritativa por `ProjectCatalogService.validate_project_profiles`.
- **Retiro de asignación obsoleta en administración**: Retirar de `AdminModelsComponent` la sección «Asignación por proyecto» y su código asociado, consolidando a `Proyectos` como la única fuente de verdad autoritativa de asignaciones bajo el Contrato Rector 2.0.

## Capabilities

### Modified Capabilities
- `project-agent-configuration`: Exige feedback de error directo e interactivo dentro de los modales de creación y edición, construcción de perfiles canónicos completos sin contaminación entre proyectos, y validación armónica entre harnesses locales de CLI y el registro de proveedores externos.
- `provider-model-administration-ui`: Retira la sección de asignación de roles por proyecto de la pantalla administrativa, concentrándola exclusivamente en el catálogo administrativo y estado de harnesses.

## Impact

- Frontend: `frontend/src/app/features/proyectos/proyectos.component.ts` y `frontend/src/app/features/admin-models/admin-models.component.ts`.
- Backend: `src/minime/api/app.py`.
- Pruebas unitarias de Angular/Node, pruebas de backend y validaciones E2E con Playwright.
