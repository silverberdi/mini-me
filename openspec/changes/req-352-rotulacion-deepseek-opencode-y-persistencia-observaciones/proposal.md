# Proposal: Rotulación explícita de DeepSeek vía OpenCode y eliminación de caducidad artificial de observaciones

## Why
En la vista de proyectos, los modelos de DeepSeek directo figuraban bajo el grupo `DeepSeek (API directa)` sin mención al harness `opencode`, impidiendo su descubrimiento al filtrar por `opencode`. Adicionalmente, el backend `CanonicalProfileResolver` imponía una expiración fija de 24 horas (`freshness=24h`), provocando que tras un día sin pulsar manualmente «Actualizar estado de harnesses», el registro o edición de proyectos fallara con `reviewer: model observation is stale`.

## What Changes
- En `ProyectosComponent` (`proyectos.component.ts`), rotular DeepSeek directo como `DeepSeek — API directa (vía OpenCode)` en su grupo y `DeepSeek — Flash (API directa vía OpenCode)` en sus opciones y mapeos, asegurando su aparición al buscar tanto `deepseek` como `opencode`.
- En `CanonicalProfileResolver` (`provider_registry.py` y `app.py`), eliminar la expiración artificial de 24 horas (`freshness=None` por defecto), garantizando que los modelos habilitados por el operador permanezcan utilizables sin requerir refrescos diarios manuales.
