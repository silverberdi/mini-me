# Tasks

## 1. Autoridad, inventario y persistencia mínima

- [x] 1.1 Confirmar F6 cerrado, autorización durable de #189/Change `gacela-07-capacidades-diferidas`, identidad de repositorio/worktree y eliminación gobernada de `disabled`; verificar el preflight fail-closed y el registro auditable.
- [x] 1.2 Inventariar callers, writers, rutas API/UI, adaptadores, tablas, migraciones, skills y pruebas de F2–F6 que cubren admisión, pausa, proyecto, Request, normalización y métricas; verificar el inventario con búsquedas estáticas y trazas de ejecución.
- [x] 1.3 Diseñar y aplicar solo las migraciones PostgreSQL necesarias para transición pendiente, selección exclusiva, idempotencia y versión remota; verificar rollback y preservación de Runs, Worktrees, auditoría y migraciones aplicadas con pruebas sobre datos representativos.

## 2. Selección exclusiva y transiciones diferidas

- [x] 2.1 Integrar selección de proyecto ejecutor y bloqueo de nuevas admisiones con la autoridad de acciones/admisión existente; verificar que dos proyectos concurrentes producen un único ejecutor y ningún scheduler paralelo.
- [x] 2.2 Implementar solicitudes de cambio de proyecto y pausas globales/por proyecto como transiciones diferidas hasta PR2 y cierre remoto, con aplicación inmediata en idle; verificar continuidad de Run/Job/Worktree y ausencia de nuevas admisiones durante la transición.
- [x] 2.3 Añadir CAS/locks, reanudación e idempotencia para repetir o competir solicitudes de transición; verificar rechazo de estado obsoleto y ausencia de procesos terminados, Runs duplicados o efectos repetidos.

## 3. Gestión remota y normalización de Requests

- [x] 3.1 Extender el contrato del proveedor de tickets para crear, editar, desactivar, reactivar y eliminar lógicamente con confirmación remota, manteniendo identidad, auditoría y exclusión FIFO; verificar cada estado permitido y que nunca se ejecuta borrado físico.
- [x] 3.2 Aplicar la frontera de admisión durable y la matriz de estados, incluyendo aclaraciones `HUMAN_REQUIRED` e inmutabilidad de finalizados; verificar que mutaciones no autorizadas fallan antes de cualquier llamada remota.
- [x] 3.3 Conectar el formulario de título, descripción y aceptación natural con la capacidad F4 existente; verificar preservación literal/procedencia, publicación Gherkin antes de Explore, control de versiones y elevación de ambigüedad material.
- [x] 3.4 Cubrir concurrencia remota, relectura de versión y reintentos idempotentes; verificar que una edición remota concurrente no se sobrescribe ni duplica comentarios o mutaciones.

## 4. Proyecciones, contexto y UI autorizada

- [x] 4.1 Conectar Dashboard/Proyectos/Backlog a estados de transición, pausa efectiva, Request y autoridad remota sin confundirlos con F2; verificar permisos backend y estados disabled/unavailable en navegador real.
- [x] 4.2 Implementar proyecciones de cuota, iteraciones, aclaraciones, tiempos, tokens/costo y contexto documental solo desde fuentes y denominadores verificables; verificar que ausencia se muestra como unavailable y no como cero/progreso ficticio.
- [x] 4.3 Añadir edición documental versionada únicamente por la ruta autorizada, con diff/guardado/cancelación y trazabilidad; verificar rechazo de paths arbitrarios y protección ante estado obsoleto.

## 5. Seguridad, retiro y evidencia E2E

- [x] 5.1 Ejecutar pruebas unitarias, contrato, permisos, concurrencia, idempotencia, migración y regresión de los contratos reutilizados; verificar resultados y fallos esperados sin degradar aserciones.
- [x] 5.2 Ejecutar E2E auténtico con un proveedor compatible para admisión, transición, mutación remota, normalización, `HUMAN_REQUIRED`, métrica no disponible y efectos persistidos; conservar invocación, resultado, efecto y SHA inmutable.
- [x] 5.3 Migrar consumidores de cualquier ruta sustituida y retirar callers/writers/código/DB muerto dentro de este Change; verificar ausencia de rutas duplicadas con censo estático y repetir toda la suite E2E después del retiro.
- [x] 5.4 Preparar revisión independiente read-only y evidencia de PR1/PR2 conforme al contrato F3; verificar que no se declara completitud sin evidencia real, autorización humana de merge y cierre documental gobernado.
