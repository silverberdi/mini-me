# Proposal: Habilitar OpenCode para thinking, selector de esfuerzo independiente, filtrado por operador y mejora visual en proyectos

## Why

Al configurar y registrar proyectos en mini me, los operadores enfrentan fricciones que impiden o degradan la experiencia operativa:
1. OpenCode fue históricamente restringido a `execution` e `independent_review`, bloqueando su uso para `thinking` (exploración / propuesta de OpenSpec), a pesar de que sus modelos son plenamente capaces de razonar.
2. El selector de modelos expone cientos de modelos descubiertos en crudo en vez de restringirse a los modelos que el operador habilitó (`is_enabled: true`) en Administración.
3. El esfuerzo de razonamiento (`effort`) se colapsó a un valor fijo (`medium`), perdiendo el control de variantes (`low`, `medium`, `high`).
4. El dropdown `model-combobox` está restringido a ~200px y trunca nombres largos, dificultando identificar proveedor y modelo.
5. El formulario permite enviar perfiles con modelos no resueltos, disparando excepciones de backend (`ValueError("Canonical provider and harness are required...")`).

## What Changes

- **Habilitación de OpenCode para `thinking`**:
  - Incorporar el rol `thinking` en `opencode_adapter.py`, `agent_runner.py`, `provider_adapter.py` y `config/minime.yaml`.
  - Asignar la capacidad canónica `"thinking": true` a los modelos descubiertos por el arnés OpenCode.
- **Filtrado del catálogo por modelos habilitados**:
  - Filtrar `/api/v1/catalogs/agents` (o la carga en `ProyectosComponent`) para que solo retorne modelos con `is_enabled == True` en `provider_model_registry`, preservando todos los proveedores activos (Codex, Antigravity, OpenCode).
- **Selector de esfuerzo independiente (Radio buttons)**:
  - Incorporar un control de radio (`Bajo` | `Medio` | `Alto`) junto a cada uno de los 4 roles en el formulario de proyectos, sin duplicar registros en el desplegable.
  - Persistir el esfuerzo seleccionado en `profile.effort` y transmitirlo en la invocación del arnés.
- **Ampliación visual y legibilidad en `model-combobox`**:
  - Ampliar el menú flotante a `min-w-[360px] max-w-[480px]` con `z-50` y etiquetas completas con tooltips.
- **Validación reactiva de formulario**:
  - Bloquear el envío en `ProyectosComponent` si alguno de los 4 roles requeridos no tiene una opción válida y resuelta.

## Capabilities

### Modified Capabilities
- `opencode-cli-adapter`: Habilitar el rol `thinking` para OpenCode junto con `execution` e `independent_review`.
- `project-agent-configuration`: Exponer únicamente modelos habilitados por el operador en el selector, permitir selección de esfuerzo independiente por rol, mejorar legibilidad del selector y validar perfiles antes del envío.

## Impact

- Código afectado:
  - Backend: `src/minime/services/opencode_adapter.py`, `src/minime/services/agent_runner.py`, `src/minime/adapters/provider_adapter.py`, `src/minime/services/provider_registry.py`, `src/minime/api/app.py`, `config/minime.yaml`, `config/minime.example.yaml`.
  - Frontend: `frontend/src/app/shared/model-combobox.component.ts`, `frontend/src/app/features/proyectos/proyectos.component.ts`.
- Pruebas afectadas:
  - `tests/test_opencode_adapter.py`, `tests/test_provider_model_registry.py`, `tests/test_project_catalog_service.py`, `frontend/e2e/project-model-combobox.spec.ts`.
