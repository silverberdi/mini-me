## Context

En `ProyectosComponent`, los modales de creación y edición utilizan un overlay de pantalla completa (`fixed inset-0 z-50 bg-slate-950/80`). Al emitirse un mensaje de error (`actionMsg`), este se renderizaba fuera del modal, en el contenedor principal de la vista, quedando inaccesible y oculto bajo el backdrop oscuro.
Asimismo, `buildProfile` utilizaba `this.refresh.activeProject()?.agent_profiles?.[role]`, lo que provocaba que al crear un proyecto nuevo se heredaran perfiles existentes de `mini-me` en lugar de instanciar un perfil canónico independiente con `provider_id` y `harness_id`.
En el backend (`src/minime/api/app.py`), `_validate_live_canonical_profiles` forzaba la validación de todos los roles contra `CanonicalProfileResolver` en la tabla `provider_model_registry`. Debido a que dicha tabla solo alberga modelos de proveedores externos (OpenCode, OpenRouter, Ollama), la asignación legítima de harnesses locales (`codex` o `antigravity`) fallaba con `ValueError: thinker: model is absent from provider catalog`.
Por último, `AdminModelsComponent` contenía una sección legacy «Asignación por proyecto» con desplegables vacíos y métodos muertos (`selectProject`, `saveRoleAssignments`, `modelsForRole`), duplicando innecesariamente la responsabilidad de `Proyectos`.

## Goals / Non-Goals

**Goals:**
- Mostrar un banner de alerta/error reactivo dentro de ambos modales (`#createProjectModal` y `#editProjectModal`) directamente visible sobre los botones de confirmación y cancelación.
- Mantener el formulario abierto ante errores para permitir corregir campos o perfiles sin perder lo diligenciado.
- Garantizar que `buildProfile` al registrar un proyecto nuevo (`isNew = true`) construya perfiles canónicos autónomos para los 4 roles (`thinking`, `execution`, `independent_review`, `fallback`), asignando `provider_id`, `harness_id`, `model_id: targetModelId`, `effort` y `route`.
- En edición de proyecto, regenerar cualquier perfil existente que carezca de `provider_id` o `harness_id` canónicos.
- En el backend (`_validate_live_canonical_profiles`), condicionar la llamada a `CanonicalProfileResolver` únicamente para aquellos roles cuyos harnesses o proveedores están gobernados por el registro de proveedores externos (`provider_model_registry`), permitiendo que `ProjectCatalogService.validate_project_profiles` ejerza su autoridad completa sobre harnesses locales instalados.
- Eliminar de `AdminModelsComponent` la plantilla HTML, métodos, propiedades y tests obsoletos de «Asignación por proyecto».

**Non-Goals:**
- Modificar la estructura de base de datos ni los esquemas de persistencia existentes.
- Alterar la tabla de modelos o el estado de harnesses en `AdminModelsComponent`.

## Decisions

### 1. Banner de error en el modal enlazado a `actionMsg`
- **Decisión:** Mantener `actionMsg` como señal reactiva pero renderizar un bloque de feedback de error con `role="alert"` dentro de la estructura de cada modal, ubicado de forma prominente antes del bloque de botones.
- **Alternativa considerada:** Modales anidados de confirmación. Rechazado: añade complejidad innecesaria contraria a KISS.

### 2. Parámetro `isNew` en `buildProfile` y validación canónica de `existing`
- **Decisión:** `buildProfile(role, modelId, effortVal, isNew = false)`. Si `isNew` es verdadero, `existing` es `null`. Si `isNew` es falso, solo se reutiliza `existing` si `existing.provider_id && existing.harness_id` están presentes. En todos los casos, se asegura `model_id: targetModelId` (variante resuelta).

### 3. Delimitación de `_validate_live_canonical_profiles` en backend
- **Decisión:** Solo someter a `CanonicalProfileResolver` aquellos roles cuyo harness/proveedor esté gestionado en `provider_model_registry` (por ejemplo `opencode` o proveedores REST). Si un rol usa harnesses de CLI locales nativos (`codex`, `antigravity`), se omite la búsqueda en `provider_model_registry` y se confía en la validación autoritativa exhaustiva de `ProjectCatalogService.validate_project_profiles` (que verifica binarios locales, capacidades, modelos, esfuerzos y OpenSpec).

### 4. Retiro total de la sección «Asignación por proyecto» en `AdminModelsComponent`
- **Decisión:** Poda limpia del template y código TypeScript asociado a asignaciones en `admin-models.component.ts`. `ProyectosComponent` queda como la única autoridad en frontend para la configuración de proyectos y perfiles.

## Risks / Trade-offs

- [Riesgo de regresión en tests unitarios existentes de `AdminModelsComponent`]: Se actualizarán los tests unitarios (`admin-models.component.spec` o `tests/*.test.mjs`) que probaban la sección retirada para validar que la pantalla administrativa se enfoque exclusivamente en la visualización de harnesses y gobernanza del catálogo de modelos.
- [Riesgo de perfiles incompletos en formularios]: La validación reactiva `isFormValid` en `ProyectosComponent` continuará garantizando que no se envíen roles vacíos.
