# Design: Unificar y hacer buscable el catálogo de modelos al configurar proyectos (Ref #336)

## Context

Actualmente, al abrir el modal de creación o edición de proyectos en `ProyectosComponent`, el componente inicializa con una lista estática en duro (`this.availableModels` con ~20 modelos de Codex y Antigravity) y luego invoca `loadAgentsCatalog()` contra `/api/v1/catalogs/agents`. Dicha petición ejecuta en el backend comandos CLI de introspección (`opencode models`), devolviendo cientos de modelos, incluidos proveedores de los cuales el operador no tiene credenciales ni acceso.

En el frontend, la función de mapeo asume erróneamente que todos los modelos derivados de OpenCode corresponden a DeepSeek, renombrando modelos de OpenRouter como `DeepSeek {Nombre} — OpenRouter`. Asimismo, los campos de selección de los 4 roles (`thinking`, `execution`, `independent_review`, `fallback`) son elementos `<select>` nativos sin capacidad de búsqueda por texto ni filtrado por proveedor.

## Goals / Non-Goals

**Goals:**
- Filtrar en el backend los modelos descubiertos por el harness OpenCode, restringiendo la salida a proveedores con credenciales y acceso efectivamente configurados (DeepSeek directo, OpenRouter, etc.).
- Almacenar en caché en el backend el catálogo descubierto de agentes/modelos con un TTL adecuado (10 minutos) para evitar ejecuciones repetidas de procesos CLI al abrir formularios.
- Eliminar la lista estática duplicada en el frontend, unificando la fuente de datos en el catálogo autoritativo.
- Proveer un selector de modelos interactivo y buscable con soporte de teclado (filtrado en tiempo real, navegación con flechas, selección con Enter, cierre con Escape).
- Etiquetar claramente cada opción con la estructura `Proveedor — Modelo (Harness)` preservando la identidad real de OpenRouter y DeepSeek directo sin prefijos espurios.
- Preservar las asignaciones preexistentes de proyectos sin sobreescrituras silenciosas.

**Non-Goals:**
- No alterar el almacenamiento ni la gestión de API keys o credenciales seguras.
- No modificar las reglas de inferencia ni la ejecución de agentes en el orquestador.
- No reasignar automáticamente los modelos de proyectos históricos.

## Decisions

### 1. Filtrado de modelos en `ProjectCatalogService` y adaptador OpenCode
- **Decisión**: Al introspeccionar modelos en OpenCode, el servicio comprobará la presencia de credenciales o configuración activa para cada proveedor aguas arriba (por ejemplo `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, o configuración en `settings.json` / entorno). Los modelos de proveedores no configurados serán excluidos del catálogo público.
- **Alternativa descartada**: Exponer todos los modelos retornados por la CLI y dejar que el usuario intente seleccionarlos, lo que produce fallos tardíos de ejecución por falta de API keys.

### 2. Caché en memoria del catálogo de agentes en backend
- **Decisión**: `ProjectCatalogService` conservará una caché en memoria de `agent_catalog` con invalidación por TTL (10 minutos) o cuando se actualice la configuración administrativa de modelos.
- **Alternativa descartada**: Consultar `shutil.which` y ejecutar procesos CLI síncronos/asíncronos en cada petición HTTP `GET /api/v1/catalogs/agents`.

### 3. Selector buscable accesible en `ProyectosComponent`
- **Decisión**: Implementar un componente/control de selección desplegable interactivo con campo de texto de búsqueda integrado. El operador puede escribir "Claude", "DeepSeek", "OpenRouter", "Codex" o "Qwen" para filtrar al instante la lista combinada, navegar con flechas y seleccionar con Enter o clic.
- **Alternativa descartada**: Mantener el `<select>` nativo que obliga al usuario a desplazarse manualmente por una lista de decenas de opciones.

### 4. Normalización de etiquetas y proveedores
- **Decisión**: Los modelos de OpenRouter se agruparán bajo el proveedor `OpenRouter` con el nombre legítimo del modelo aguas arriba (ej. `OpenRouter — Claude 3.5 Sonnet`, `OpenRouter — Qwen 2.5 Coder 32B`, `OpenRouter — DeepSeek V4 Pro`). DeepSeek por API directa se agrupará bajo `DeepSeek` con la indicación `API directa`. Codex y Antigravity mantendrán sus identificadores observados.
- **Alternativa descartada**: Parseo heurístico de cadenas por regex en el frontend que antepone "DeepSeek" a cualquier ruta de OpenRouter.

## Risks / Trade-offs

- **[Riesgo]**: Perfiles de proyectos existentes que usen identificadores antiguos (ej. `claude-sonnet-5-5-medium` o alias sin prefijo de proveedor).
  → **Mitigación**: El resolver del backend y el frontend buscarán coincidencia por ID exacto y fallback a las rutas canónicas del catálogo, preservando el valor original si ya está guardado en PostgreSQL sin mutarlo al editar otros campos del proyecto.
