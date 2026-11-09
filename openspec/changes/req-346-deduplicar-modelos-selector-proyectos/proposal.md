## Why

En el modal de configuración de proyectos, las variantes de esfuerzo de arneses como Antigravity (que exponen identificadores individuales como `model-low`, `model-medium` y `model-high`) se listan triplicadas en el combobox con etiquetas visuales idénticas. Esto crea ruido visual y confusión en el operador al interactuar con el selector.

## What Changes

- Deduplicar en `loadAgentsCatalog` las opciones de modelos por proveedor y familia base, presentando un único registro por modelo en el desplegable.
- Indexar en `ModelOption` las variantes de esfuerzo (`variants: Record<string, string>`) para resolver el identificador exacto de modelo según el esfuerzo elegido en los radio buttons.
- Actualizar `buildProfile` para que seleccione automáticamente el identificador de modelo correcto (por ejemplo `claude-sonnet-5-5-high`) cuando el arnés exige codificar el esfuerzo en el nombre del modelo.
- Actualizar `ModelComboboxComponent` para que reconozca la selección activa independientemente de la variante de esfuerzo asignada al rol.

## Capabilities

### Modified Capabilities
- `project-agent-configuration`: Deduplica visualmente las opciones del catálogo de modelos por familia base y mapea reactivamente la selección de esfuerzo al identificador de variante requerido por el arnés.

## Impact

- `frontend/src/app/shared/model-combobox.component.ts`: Interfaz `ModelOption` enriquecida con `variants` y método `isSelected(m)` adaptado para reconocer variantes.
- `frontend/src/app/features/proyectos/proyectos.component.ts`: Agrupación única en `loadAgentsCatalog`, resolución en `buildProfile`, `isFormValid` y `resolveProviderForModel`.
- Pruebas unitarias de frontend (`frontend/tests/unified-searchable-model-catalog.test.mjs`) y prueba E2E de Playwright (`frontend/e2e/project-model-combobox.spec.ts`).
