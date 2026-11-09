# Technical Design: Habilitar OpenCode para thinking, selector de esfuerzo independiente, filtrado por operador y mejora visual en proyectos

## Context

Ver `proposal.md` para motivación y antecedentes.
Actualmente:
- `opencode_adapter.py` y `agent_runner.py` restringen los roles a `execution` e `independent_review`.
- En `provider_model_registry`, los modelos de OpenCode no reciben la capacidad canónica `"thinking": true`, lo que causa que `CanonicalProfileResolver` los rechace para `thinker`.
- `/api/v1/catalogs/agents` no filtra por los modelos con `is_enabled: true` en `provider_model_registry`.
- En el frontend, el esfuerzo se asigna estáticamente sin control del operador y el selector colapsó todos los esfuerzos a un único registro `medium`.
- `model-combobox` sufre de truncamiento y un ancho rígido (~200px) derivado del grid del modal.

## Goals / Non-Goals

**Goals:**
- Habilitar formalmente a OpenCode para ejecutar el rol `thinking` (operaciones `explore` y `propose`), tanto a nivel de adaptador como de resolvedor canónico.
- Filtrar la lista de modelos de selección en proyectos según el flag `is_enabled: true` del registro administrativo persistido.
- Agregar control de radio independiente (`Bajo`, `Medio`, `Alto`) por rol en la UI de proyectos, persistiendo `effort` en el perfil de cada rol.
- Mejorar el diseño del combobox con ancho mínimo de 360px a 480px y tooltips completos.
- Validar el formulario de creación y edición en el cliente para evitar peticiones con perfiles no resueltos.

**Non-Goals:**
- No se modifica la estructura de la base de datos ni se alteran los contratos de persistencia de perfiles (el campo `effort` ya existe y está soportado en PostgreSQL).
- No se elimina el soporte de OpenCode para `execution` ni `independent_review`.
- No se modifica la lógica de revisión independiente (principio de independencia estricto).

## Decisions

### 1. Desbloqueo de OpenCode para `thinking`
- **Decisión**: Extender `SUPPORTED_ROLES` en `src/minime/services/opencode_adapter.py` para incluir `"thinking"`. En `agent_runner.py`, mapear `role in ("thinker", "thinking")` a `opencode_role = "thinking"` con operación `propose` (o `explore`).
- **Alternativa descartada**: Crear un wrapper separado para OpenCode en modo thinking. Descartada por violar DRY y añadir capas innecesarias cuando el arnés ya soporta las operaciones nativas.

### 2. Capacidad Canónica de Thinking en Modelos Descubiertos
- **Decisión**: En `src/minime/api/app.py` (inspección de arnés) y `provider_registry.py`, asignar `"thinking": True`, `"workflow": True`, `"file_edit": True`, `"read_only_review": True` a las capacidades de los modelos descubiertos de OpenCode que son de uso general.
- **Alternativa descartada**: Requerir que el operador configure manualmente capacidades personalizadas en cada modelo. Descartada por generar fricción innecesaria.

### 3. Filtrado de Catálogo en Proyectos por `is_enabled`
- **Decisión**: Modificar `/api/v1/catalogs/agents` para cruzar con `provider_model_registry` o incluir un parámetro `only_enabled=true` de modo que los modelos que el operador deshabilitó no se envíen a la UI de proyectos.
- **Alternativa descartada**: Filtrar únicamente en el cliente Angular. Descartada para mantener consistencia de seguridad y no transferir payloads innecesarios.

### 4. Selector de Esfuerzo Independiente mediante Radio Buttons
- **Decisión**: Colocar un grupo de radio buttons compacto (`Bajo` [low], `Medio` [medium], `Alto` [high]) junto a cada rol en el formulario de proyectos. El combobox solo selecciona el `model_id` (sin duplicaciones). Al guardar, se asocia `effort: selectedEffort[role]`.
- **Alternativa descartada**: Duplicar cada modelo en el dropdown como `Modelo [HIGH]`, `Modelo [MED]`, `Modelo [LOW]`. Descartada explícitamente por el operador para evitar duplicación y ruido en el catálogo.

### 5. Ancho del Menú Flotante de `model-combobox`
- **Decisión**: Usar clases Tailwind `w-max min-w-[360px] max-w-[480px] z-50 shadow-2xl` para el popup del combobox y añadir atributo `title` en las opciones con el texto completo.
- **Alternativa descartada**: Ensanchar todo el modal a pantalla completa. Descartada para preservar la estética compacta del centro de control.

## Risks / Trade-offs

- [Riesgo]: Un modelo podría no soportar niveles de esfuerzo (por ejemplo modelos locales o de bajo parámetro).
  → *Mitigación*: El backend tolera esfuerzo opcional o lo transmite según soporte; el valor por defecto sigue siendo `medium`.
- [Riesgo]: Proyectos antiguos sin `effort` explícito.
  → *Mitigación*: Se preserva el valor existente o se asume `medium` de forma retrocompatible.
