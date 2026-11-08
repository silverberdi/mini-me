# Tasks: Unificar y hacer buscable el catálogo de modelos al configurar proyectos (Ref #336)

## 1. Backend: Filtrado de Proveedores con Acceso Configurado y Caché de Catálogo

- [x] 1.1 Filtrar en `ProjectCatalogService.agent_catalog` (y adaptador OpenCode) los modelos descubiertos para exponer únicamente proveedores con credenciales o acceso configurado (ej. DeepSeek directo, OpenRouter), omitiendo proveedores no configurados y modelos nativos sin acceso activo.
- [x] 1.2 Implementar caché en memoria para `agent_catalog` en `ProjectCatalogService` con TTL de 10 minutos para evitar ejecuciones repetidas de introspección CLI (`opencode models`) al abrir modales en la PWA.
- [x] 1.3 Preservar en `/api/v1/catalogs/agents` las rutas canónicas y nombres aguas arriba sin alterar las credenciales ni exponer secretos en respuestas o logs.

## 2. Frontend: Eliminación de Lista Estática Inicial y Normalización de Proveedores

- [x] 2.1 Eliminar el arreglo inicial hardcodeado estático de modelos en `ProyectosComponent`, unificando la fuente de datos exclusivamente en la respuesta autoritativa del backend.
- [x] 2.2 Corregir el formateo y agrupación de modelos para que OpenRouter figure como proveedor independiente con su nombre aguas arriba (ej. `OpenRouter — Claude Sonnet 3.5`, `OpenRouter — Qwen 2.5`) sin forzar el prefijo "DeepSeek".
- [x] 2.3 Mantener la distinción explícita entre DeepSeek directo (`DeepSeek — {Modelo} (API directa)`) y DeepSeek vía OpenRouter (`OpenRouter — DeepSeek V4 Pro`), asociando a cada uno su credencial y ruta respectiva.
- [x] 2.4 Preservar las asignaciones preexistentes de proyectos al editar, impidiendo mutaciones silenciosas de perfiles guardados.

## 3. Frontend: Selector de Modelos Buscable e Interactivo

- [x] 3.1 Implementar en `ProyectosComponent` (o componente compartido) un selector desplegable buscable con soporte de filtrado instantáneo por texto (búsqueda por proveedor o nombre de modelo).
- [x] 3.2 Añadir navegación por teclado (flechas arriba/abajo, Enter para seleccionar, Escape para cerrar) y accesibilidad adecuada (`role="combobox"` / `aria-expanded`).
- [x] 3.3 Integrar el selector buscable en los 4 roles del formulario de creación y del formulario de edición (`thinking`, `execution`, `independent_review`, `fallback`).

## 4. Pruebas y Verificación

- [x] 4.1 Añadir prueba unitaria de backend verificando que el catálogo de agentes filtra proveedores sin credenciales y cachea las respuestas de descubrimiento.
- [x] 4.2 Añadir prueba unitaria de frontend en `frontend/tests/` certificando la ausencia de lista estática duplicada, la separación correcta de OpenRouter y la operabilidad del selector buscable.
- [x] 4.3 Añadir o actualizar prueba E2E de Playwright verificando la búsqueda y selección de modelos al crear/editar un proyecto.
- [x] 4.4 Ejecutar las suites de pruebas (`pytest` en backend y `npm test` en frontend) asegurando 100% de éxito.
