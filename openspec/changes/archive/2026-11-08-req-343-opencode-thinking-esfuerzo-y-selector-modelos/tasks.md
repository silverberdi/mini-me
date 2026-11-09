## 1. Backend: Arnés OpenCode para rol Thinking y Capacidades de Modelos

- [x] 1.1 Extender `SUPPORTED_ROLES` en `src/minime/services/opencode_adapter.py` para incluir `"thinking"` y permitir despacho de operaciones `propose` y `explore`.
- [x] 1.2 Actualizar `src/minime/services/agent_runner.py` para autorizar y despachar el rol `thinking` en OpenCode con operación `propose` (o `explore`).
- [x] 1.3 Declarar el rol `thinking` en `OpenCodeProviderAdapter.supported_roles` (`src/minime/adapters/provider_adapter.py`) y en `config/minime.yaml` / `config/minime.example.yaml`.
- [x] 1.4 Asignar capacidades canónicas (`thinking: true`, `workflow: true`, `file_edit: true`, `read_only_review: true`) a las observaciones descubiertas por OpenCode en `src/minime/api/app.py` y `provider_registry.py` para que `CanonicalProfileResolver` valide `thinker`.

## 2. Backend: Filtrado de Catálogo por Modelos Habilitados

- [x] 2.1 Actualizar `/api/v1/catalogs/agents` en `src/minime/api/app.py` y `ProjectCatalogService` para filtrar modelos devolviendo únicamente los que tienen `is_enabled == True` en `provider_model_registry` (o permitir flag de filtrado).
- [x] 2.2 Agregar pruebas unitarias en `tests/test_opencode_adapter.py`, `tests/test_provider_model_registry.py` y `tests/test_project_catalog_service.py` verificando el rol `thinking` en OpenCode y el filtrado por `is_enabled`.

## 3. Frontend: Selector de Esfuerzo Independiente y Validación de Formulario

- [x] 3.1 Incorporar en `frontend/src/app/features/proyectos/proyectos.component.ts` controles de radio independientes (`Bajo`, `Medio`, `Alto`) para cada rol (`thinking`, `execution`, `independent_review`, `fallback`), inicializados con el esfuerzo existente o `medium`.
- [x] 3.2 Modificar `buildProfile` y el guardado de proyecto para empaquetar el esfuerzo seleccionado de cada rol en `profile.effort` sin duplicar modelos en el catálogo.
- [x] 3.3 Validar reactivamente en `proyectos.component.ts` que los 4 roles requeridos tengan un modelo resuelto válido antes de habilitar los botones de guardado / creación.

## 4. Frontend: Ampliación Visual y Legibilidad en `model-combobox`

- [x] 4.1 Modificar `frontend/src/app/shared/model-combobox.component.ts` para que el menú emergente se despliegue con `w-max min-w-[360px] max-w-[480px] z-50` y sombra adecuada.
- [x] 4.2 Añadir atributo `title` en las opciones y en la selección activa para permitir lectura completa de proveedor, arnés y modelo.

## 5. Verificación y Pruebas E2E

- [x] 5.1 Ejecutar suite de pruebas de backend con pytest (`pytest tests/test_opencode_adapter.py tests/test_provider_model_registry.py tests/test_project_catalog_service.py`).
- [x] 5.2 Ejecutar suite de pruebas de frontend (`npm test` o `npm run test:unit`).
- [x] 5.3 Ejecutar y actualizar la prueba E2E de Playwright (`npx playwright test project-model-combobox.spec.ts`) verificando el combobox ampliado, el control de esfuerzo y la persistencia de roles.
