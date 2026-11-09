# Design: Rotulación explícita de DeepSeek vía OpenCode y eliminación de caducidad artificial de observaciones

## Contexto
En `ProyectosComponent`, los modelos de OpenAI, Anthropic y Google indican explícitamente el harness de ejecución (`(vía Codex)`, `(vía Antigravity)`), al igual que OpenRouter (`(vía OpenCode)`). Sin embargo, los modelos de DeepSeek directo figuraban como `DeepSeek (API directa)`, lo que generaba confusión en el operador y ocultaba el modelo al buscar `opencode`.
En el backend, `CanonicalProfileResolver` poseía un valor predeterminado `freshness = timedelta(hours=24)` que provocaba que tras 24 horas de inactividad de descubrimiento, cualquier intento de asignar modelos externos fallara con `reviewer: model observation is stale`.

## Decisiones Técnicas

1. **Frontend (`proyectos.component.ts`):**
   - Actualizar `formatModelEntry`:
     - `label: DeepSeek — ${cleanName || 'V4 Pro'} (API directa vía OpenCode)`
     - `group: DeepSeek — API directa (vía OpenCode)`
   - Actualizar el diccionario de fallback en `getRoleModel` para mantener consistencia con los IDs persistidos.

2. **Backend (`provider_registry.py` y `app.py`):**
   - En `CanonicalProfileResolver.__init__`, establecer `freshness: timedelta | None = None` por defecto.
   - En `_validate_live_canonical_profiles` (`app.py`), invocar `CanonicalProfileResolver(uow.provider_model_registry, freshness=None)`.
   - Si `freshness` es `None`, no se evalúa `last_observed_at < utc_now() - self.freshness`. Los modelos habilitados (`is_enabled: true`) con estado `available` permanecen válidos.
