# Proposal

## Why

F5 dejó controles visuales honestamente deshabilitados para operaciones que necesitan autoridad de backend: proyecto ejecutor único, pausas diferidas, gestión segura de Requests, normalización de entrada humana y métricas verificables. La autorización operativa registrada para la Issue #189 habilita ahora la planificación de F7, dependiente del cierre de F6, para conectar esas capacidades con las operaciones reales sin duplicar componentes ni alterar F6.

## What Changes

- Habilitar, bajo una autorización durable y con la etiqueta `disabled` retirada solo por el flujo gobernado, la operación de un único proyecto ejecutor por instalación.
- Implementar cambio de proyecto y pausas globales/por proyecto como transiciones diferidas: ningún Change iniciado se interrumpe y no se admite trabajo nuevo hasta completar PR2 y cierre remoto.
- Añadir gestión agnóstica del proveedor para crear, editar, desactivar, reactivar y eliminar lógicamente Requests, preservando historia remota y excluyendo bajas lógicas del FIFO.
- Aplicar la matriz de estados: solo Requests no iniciados admiten edición libre, desactivación o eliminación lógica; los admitidos/en curso usan `HUMAN_REQUIRED` para aclaraciones y los finalizados son inmutables.
- Conectar el formulario humano con la normalización F4 existente, preservando cuerpo/procedencia y elevando ambigüedades materiales sin exigir Gherkin al operador.
- Exponer únicamente métricas con fuente y denominador verificables, distinguiendo ausencia de cero, y completar el contexto documental versionado solo mediante rutas autorizadas.
- Reutilizar los contratos existentes de proyectos, backlog remoto, acciones, concurrencia, PostgreSQL, Git/PR y OpenSpec nativo; retirar rutas duplicadas o controles F5 que queden sustituidos dentro de este Change, preservando historia y datos.
- **No** construir ADO, un scheduler nuevo, una cola local, un motor paralelo de orquestación, un normalizador propio, ni habilitar despliegue productivo.

## Capabilities

### New Capabilities

- `f7-functional-operations`: operaciones funcionales posteriores al MVP visual: selección exclusiva, transiciones diferidas, gestión de Requests, métricas y contexto gobernado.

### Modified Capabilities

F7 compone los contratos existentes de proyectos/backlog, intake remoto, normalización F4, acciones gobernadas y observabilidad; no modifica sus capacidades base ni crea una variante paralela. Sus nuevas operaciones se especifican en `f7-functional-operations` y deben invocarlas mediante esas autoridades existentes.

## Impact

- Afecta los adaptadores de Requests/GitHub y Git/PR, la coordinación de proyecto y admisión, acciones de operador, checkpoints de continuidad, modelos/migraciones PostgreSQL mínimos, API FastAPI y vistas F5.
- Requiere interfaces pequeñas para proveedores de tickets y Git/PR, con GitHub como implementación inicial y contratos intercambiables; no implementa ADO.
- Requiere evidencia E2E auténtica con un proveedor compatible para admisión, mutaciones remotas, normalización, transiciones diferidas, autorización y efectos observables.
- La implementación posterior deberá inventariar y retirar de forma segura cualquier writer/caller sustituido, sin borrar Issues, comentarios, auditoría, Runs, Worktrees, migraciones aplicadas ni specs archivadas.
- F7 sigue siendo una fase posterior y no se ejecuta por este artefacto de propuesta; este workflow solo prepara el Change autorizado.
