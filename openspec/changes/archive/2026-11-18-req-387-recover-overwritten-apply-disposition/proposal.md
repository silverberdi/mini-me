## Why

Un Run detenido puede conservar la decisión humana y una invocación nativa `UPDATE` completada y validada, pero haber perdido el detalle de qué disposiciones de tareas cambió cuando una versión anterior reemplazó ese checkpoint con un `UPDATE` sin cambios. El arreglo #384 evita nuevas sobrescrituras, pero no recupera Runs afectados antes de ese despliegue; reintentar a ciegas, alterar PostgreSQL manualmente o iniciar otro Run arriesga el candidato y su historial.

## What Changes

- Detectar el caso de checkpoint perdido solo cuando la evidencia persistida permita comparar la decisión humana aceptada, el snapshot de Apply, las disposiciones actuales y las invocaciones nativas asociadas al mismo Run y candidato.
- Presentar al operador esa comparación y una decisión explícita para aceptar como nuevo baseline el estado actual del Change, manteniendo pendientes o diferidas las tareas sin evidencia del candidato.
- Guardar la autorización y el nuevo baseline como una transición durable e idempotente, sin borrar ni reescribir snapshots, decisiones o invocaciones anteriores.
- Reanudar Apply una sola vez en el mismo Run, Change, rama, worktree, generación y SHA solo después de validar esa identidad y comprobar que no hay una invocación activa.
- Mantener el gate y permitir preservar o cancelar el Run cuando la identidad no coincide, hay trabajo activo o la evidencia es ambigua. No modificar PostgreSQL a mano, contadores de intentos ni iniciar otro Run.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `openspec-native-apply-and-verify`: recuperar un Run anterior a #384 con checkpoint de Update perdido mediante autorización humana y evidencia ligada al candidato.
- `openspec-orchestration-continuity`: mostrar la discrepancia y ejecutar una reanudación idempotente sin reescribir el historial ni cambiar la identidad del Run.

## Impact

- Coordinación de Apply, composición/proyección del gate humano y la presentación de evidencia existente del Run.
- Persistencia PostgreSQL existente de Runs, decisiones del operador, snapshots e invocaciones; no se anticipa una tabla nueva.
- E2E PostgreSQL/API/coordinator que demuestre comparación, autorización, conservación histórica y un único despacho de Apply para el mismo candidato, además de denegaciones ante identidad distinta, invocación activa o evidencia ambigua.
