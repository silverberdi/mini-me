# Change: Unificar y hacer buscable el catálogo de modelos al configurar proyectos (Ref #336)

## Why

Al crear o editar proyectos, el formulario en `ProyectosComponent` muestra inicialmente una lista estática hardcodeada que luego es reemplazada asíncronamente por el catálogo descubierto de `/api/v1/catalogs/agents`. La consulta de OpenCode puede arrojar un catálogo masivo sin filtrar modelos de proveedores sin credenciales activas, y el frontend confunde todos los modelos de OpenRouter etiquetándolos erróneamente bajo el prefijo "DeepSeek" (por ejemplo, "DeepSeek Claude Fable"). Además, la lista no ofrece búsqueda rápida ni discriminación clara entre proveedores aguas arriba y harnesses de ejecución.

## What Changes

- **MODIFICATION**: En el backend (`ProjectCatalogService` y `/api/v1/catalogs/agents`), el descubrimiento de modelos de OpenCode se filtra estrictamente para exponer únicamente los proveedores que disponen de acceso/credenciales configuradas (como DeepSeek directo, OpenRouter u otros configurados). No se presentan modelos de proveedores sin acceso configurado ni modelos nativos de OpenCode mientras su servicio nativo no esté operativo.
- **MODIFICATION**: El backend almacena en caché el catálogo de modelos descubierto para evitar ejecutar repetidamente comandos CLI de introspección cada vez que el operador abre el formulario de creación o edición.
- **MODIFICATION**: En el frontend (`ProyectosComponent`), se elimina la lista inicial estática hardcodeada duplicada. Tanto la creación como la edición de proyectos consumen una única fuente autoritativa de catálogo.
- **NEW CAPABILITY**: Se reemplazan los menús desplegables nativos estándar por un selector buscable con soporte de teclado, filtrado rápido por texto y visualización limpia de `Proveedor — Modelo (Harness)` (por ejemplo: `DeepSeek — DeepSeek V4 Pro (API directa)`, `OpenRouter — Claude Fable`, `OpenRouter — DeepSeek V4 Pro`, `Codex — GPT-5.6 Luna`, `Antigravity — Gemini 3.8 Flash`).
- **MODIFICATION**: Se corrigen las rutas y etiquetas para que OpenRouter figure como proveedor legítimo y el nombre del modelo aguas arriba se preserve fielmente sin forzar el prefijo "DeepSeek".
- **PRESERVATION**: Las asignaciones actuales de perfiles de proyectos se conservan intactas; la validación y guardado respetan las identidades canónicas existentes sin mutaciones silenciosas.

## Capabilities

### Modified Capabilities
- `project-agent-configuration`: Exige que el catálogo de modelos exponga únicamente proveedores con acceso configurado, diferencie limpiamente OpenRouter de DeepSeek directo y harnesses de ejecución, unifique la fuente de datos eliminando listas estáticas iniciales, y provea soporte de búsqueda interactiva por proveedor y modelo en la UI.

## Impact

- **Backend**:
  - `src/minime/services/project_catalog_service.py`: Caché de descubrimiento y filtrado de modelos de OpenCode por proveedores con credenciales configuradas; preservación de nombres canónicos aguas arriba para OpenRouter.
- **Frontend**:
  - `frontend/src/app/features/proyectos/proyectos.component.ts`: Eliminación de lista estática hardcodeada inicial; integración de selector buscable accesible con teclado; agrupación y formateo fiel de `Proveedor — Modelo`.
  - `frontend/src/app/features/proyectos/proyectos.component.html` (o template inline): Componente o dropdown buscable por rol (`thinking`, `execution`, `independent_review`, `fallback`).
- **APIs / Contratos**: `/api/v1/catalogs/agents` devuelve metadatos consistentes sin exponer credenciales ni tokens.
