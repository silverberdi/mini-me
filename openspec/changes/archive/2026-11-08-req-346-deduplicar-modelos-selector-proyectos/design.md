## Context

En el modal de proyectos, los modelos de Antigravity (Claude, Gemini) se registran en el catálogo con variantes de esfuerzo indivisibles (`-low`, `-medium`, `-high`). Cuando se normalizó la etiqueta en `formatModelEntry`, las 3 variantes resultaron con la misma etiqueta (`Antigravity — Claude SONNET.5.5`), apareciendo 3 veces consecutivas en el combobox.

## Goals / Non-Goals

**Goals:**
- Garantizar que cada familia de modelo aparezca exactamente una vez en el dropdown de selección de roles.
- Asociar las variantes de esfuerzo disponibles a la entrada única en `availableModels` (`variants: Record<string, string>`).
- Mapear de forma transparente la selección de modelo y el radio button de esfuerzo en `buildProfile` al identificador final que requiere el arnés.
- Preservar la compatibilidad con modelos que no usan variantes de sufijo (Codex, OpenCode).

**Non-Goals:**
- Modificar el protocolo de backend o la base de datos `provider_model_registry`.
- Cambiar la invocación o CLI subyacente de Antigravity.

## Decisions

1. **Deduplicación por Clave Compuesta (`providerId:label:group`)**:
   - En `loadAgentsCatalog`, se utiliza un `Map<string, ModelOption>` para acumular las variantes de esfuerzo en `variants[effort] = modelKey`. Si la variante es `medium`, se utiliza como `id` por defecto.
   - *Alternativa considerada:* Filtrar solo modelos `-medium` en backend. *Descartada:* impedirá que el operador seleccione variantes si solo tiene habilitada una variante específica.

2. **Reconocimiento de Selección Activa en `ModelComboboxComponent`**:
   - Se incorpora `isSelected(m)` en el combobox para comparar tanto `m.id === modelValue` como `m.variants && Object.values(m.variants).includes(modelValue)`. Esto asegura que al abrir la edición de un proyecto que tenga guardado `claude-sonnet-5-5-high`, el combobox reconozca y seleccione correctamente la entrada base de `Claude Sonnet 5.5`.

3. **Resolución de Identificador en `buildProfile`**:
   - Si el modelo elegido tiene `variants` para el esfuerzo seleccionado, se asigna `targetModelId = found.variants[effort]`. Si es Antigravity y no hay variante directa, se calcula `${baseName}-${effort}`. Para otros proveedores, el ID base se conserva y solo se asigna `profile.effort`.

## Risks / Trade-offs

- *[Riesgo]*: Que un proyecto histórico tenga guardado un modelo sin sufijo de esfuerzo en Antigravity.
  - *Mitigación*: `buildProfile` y `resolveProviderForModel` toleran tanto IDs con sufijo como sin sufijo.
