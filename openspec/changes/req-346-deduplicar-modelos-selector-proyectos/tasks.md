## 1. Frontend: Deduplicación y Mapeo en Catálogo y Combobox

- [x] 1.1 Extender `ModelOption` en `frontend/src/app/shared/model-combobox.component.ts` con el campo `variants?: Record<string, string>`.
- [x] 1.2 Agregar método `isSelected(m: ModelOption)` en `ModelComboboxComponent` para verificar coincidencia por ID o variante activa.
- [x] 1.3 Actualizar `loadAgentsCatalog` en `frontend/src/app/features/proyectos/proyectos.component.ts` para agrupar variantes que comparten proveedor, etiqueta y grupo en un único registro de `availableModels`.

## 2. Frontend: Resolución de Perfiles de Modelos Según Esfuerzo

- [x] 2.1 Actualizar `buildProfile` en `proyectos.component.ts` para resolver el identificador de modelo según la variante de esfuerzo seleccionada en los radio buttons.
- [x] 2.2 Adaptar `isFormValid`, `resolveProviderForModel`, `resolveAgentForModel` y `getRoleModel` para reconocer modelos a través de sus variantes.

## 3. Pruebas y Verificación E2E

- [x] 3.1 Agregar prueba unitaria en `frontend/tests/unified-searchable-model-catalog.test.mjs` verificando la deduplicación de variantes con etiquetas idénticas.
- [x] 3.2 Actualizar y ejecutar prueba E2E en `frontend/e2e/project-model-combobox.spec.ts` verificando que exista exactamente una opción por modelo en el dropdown.
