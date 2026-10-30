# Design

## Context

F5 ya presenta proyectos, backlog remoto, formularios y controles F7; F4 ya define la normalización y F3/F6 poseen continuidad de Change, PR1/PR2, gates y cierre. Este Change añade autoridad operativa detrás de esas superficies, condicionado por la autorización de la Issue #189 y el cierre de F6. La fuente de tickets sigue siendo remota; PostgreSQL conserva únicamente configuración, checkpoints, decisiones, idempotencia y evidencia mínima.

## Goals / Non-Goals

**Goals:**

- Conectar las operaciones F7 a los adaptadores y autoridades existentes, con una sola ruta efectiva por operación.
- Hacer transiciones diferidas y recuperables sin interrumpir procesos ni perder Worktrees, Runs o auditoría.
- Mantener contratos intercambiables para tickets y Git/PR, con GitHub como primera implementación.
- Probar permisos, concurrencia, idempotencia, normalización, efectos remotos y UI mediante E2E real.
- Retirar rutas sustituidas únicamente después de paridad y E2E, conservando historia y migraciones aplicadas.

**Non-Goals:**

- No crear scheduler, cola local, motor paralelo, backlog PostgreSQL, normalizador F4 alternativo ni ADO.
- No migrar a Angular, no desplegar productivo y no ejecutar F7 durante la fase de planificación.
- No convertir F2 `ACTIVE`/`PAUSED` en estado de pausa efectiva ni permitir mutaciones sin autoridad remota.

## Decisions

1. **Una autoridad de transición, no un coordinador nuevo.** Las solicitudes de selección/pausa se registran mediante la acción gobernada existente, con estado durable mínimo y CAS/locks PostgreSQL. La admisión consulta ese estado antes de seleccionar FIFO. Se descarta un scheduler paralelo porque duplicaría la autoridad y rompería la continuidad.

2. **Adaptadores remotos separados.** El proveedor de Requests y el proveedor Git/PR mantienen interfaces distintas. GitHub implementa ambos inicialmente; ADO queda fuera hasta necesidad demostrada. Las mutaciones remotas usan relectura de versión, claves idempotentes y confirmación posterior.

3. **Admisión durable como frontera de edición.** Un Request pasa a “iniciado” al persistirse la admisión durable, no al comenzar trabajo visible del agente. Antes de esa frontera se permiten operaciones limitadas; después solo aclaraciones por `HUMAN_REQUIRED` y cierre inmutable.

4. **Normalización por composición.** El formulario guarda el cuerpo/procedencia y entrega el Request al skill/capacidad F4 ya existente. F7 no interpreta ni genera Gherkin; solo verifica precondiciones, versión remota y postcondiciones antes de Explore.

5. **Proyecciones honestas.** Las métricas se calculan desde fuentes observables y denominadores explícitos. Ausencia se modela como unavailable/null, nunca como cero. Cuota/costo solo se muestran cuando la fuente técnica los confirma.

6. **Retiro seguro dentro del Change.** Antes de retirar cualquier ruta F5/F6 se hará inventario estático y dinámico de callers/writers, se probará la nueva autoridad con E2E, se migrarán consumidores y se repetirán las pruebas después del retiro. Historia remota, Runs, Worktrees, auditoría y migraciones aplicadas no se borran.

## Risks / Trade-offs

- [Una transición puede quedar esperando un Change bloqueado] → conservar checkpoint y estado pendiente, exponer la causa y reanudar por la ruta F3/F6; no cancelar procesos ni admitir trabajo nuevo.
- [La API remota puede cambiar entre lectura y escritura] → usar versión/ETag o equivalente, rechazar estado obsoleto y reintentar solo con relectura segura e idempotencia.
- [Una métrica puede parecer disponible sin denominador] → devolver unavailable y registrar fuente/razón; prohibir inferencias de UI.
- [El código legado puede tener consumidores dinámicos] → combinar censo estático con E2E/telemetría de invocación antes de retirar; marcar `RETAIN-WITH-REASON` solo con autorización explícita.
- [Una operación remota puede completarse antes de fallar la persistencia local] → usar claves idempotentes y reconciliación posterior; nunca repetir ciegamente el efecto externo.

## Migration Plan

1. Confirmar precondiciones: F6 cerrado, autorización durable de #189, identidad de repositorio/worktree y estado remoto `disabled`.
2. Inventariar APIs, adaptadores, writers, callers, tablas/migraciones y controles F5/F6 relacionados; documentar reuse/modify/retire.
3. Añadir contratos y migraciones mínimas, con rollback que preserve auditoría, checkpoints y datos remotos.
4. Integrar acciones diferidas, gestión remota, normalización F4 y proyecciones verificables detrás de permisos backend.
5. Ejecutar pruebas unitarias/contrato, concurrencia e integración; después E2E real con proveedor compatible y navegador cuando aplique.
6. Retirar rutas sustituidas, repetir las pruebas post-retiro y preparar evidencia ligada a SHA inmutable para revisión independiente.
7. El despliegue, PR/merge y cierre documental seguirán el workflow oficial y el contrato F3; esta propuesta no los ejecuta.

## Open Questions

No quedan preguntas que cambien la especificación o el enfoque. Los identificadores concretos de App/instalación GitHub, host, URLs de preview, política de rollback por proyecto y límites de presupuesto permanecen decisiones operativas del entorno y deberán resolverse por configuración/autorización antes de ejecutar tareas que los requieran.
