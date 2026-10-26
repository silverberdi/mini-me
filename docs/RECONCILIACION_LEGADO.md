# Reconciliación de documentación, specs y backlog heredados

**Autoridad vigente:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md) v1.3, [BACKLOG.md](BACKLOG.md) y [F5_UX_CONTRATO.md](F5_UX_CONTRATO.md). Este documento NO prueba que las implementaciones antiguas ya hayan sido retiradas.

## Cambio de dirección
La historia 001–022, el backlog de recuperación MM-R01–MM-R10, los tickets N01–N05 y los dossiers respectivos describen trabajo anterior con componentes y políticas que el nuevo contrato puede sustituir. Permanece como evidencia/historia técnica. **No debe tratarse como una segunda ruta vigente de ejecución.** No borrar Issues/PR, worktrees o datos operativos mediante este ajuste documental.

## Contradicciones explícitas
| Tema heredado | Dirección sustituida por contrato 1.2 | Fase responsable |
| --- | --- | --- |
| Plan MM-R01–R10 y prioridad de stages técnicos | Seis fases originales F1–F6 preservadas, un Change por fase; fases futuras F7 y F8 añadidas por decisión posterior, disabled, sin Changes aún | F1–F8 |
| Scheduler con scoring/aging, gates y backlog DB | Ticket remoto más antiguo elegible; un activo por proyecto | F1, F3, F6 |
| Codex/AGY/DeepSeek roles preasignados en core | Cuatro roles/modelos configurables, independientes | F2, F3 |
| OpenSpecGenerator y creación propia de specs | Agent-side native propose/update | F1 |
| Python OpenSpecSyncService y archive por movimiento de carpetas | Agent-side native sync/archive | F1, F3 |
| Verificadores semánticos sustitutos de workflow verify | Agent-side native verify + tests pertinentes | F1, F3 |
| Revisión código siempre obligatoria por DeepSeek | Propuesta siempre revisada; revisión de código condicional según política; revisor distinto/solo lectura | F2, F3 |
| Merge solo fuera de UI / segunda publicación sin contrato | Merge implementación autorizado por humano en UI; PR documental mergeable automáticamente si Git lo permite | F3, F5 |
| mini me responsable de despliegue/productivo/postdeploy | Despliegue responsabilidad exclusiva de CI/CD de cada proyecto | F1, F3, F6 |
| Intervención humana como bloqueo bruto | Opciones originales; pensamiento contextual si no hay opciones, humano cuando sea necesario | F3, F5 |
| UI histórica centrada en pipeline viejo | Cinco vistas independientes con **Dashboard/Proyectos** como únicos destinos principales; Trabajo, Trabajo actual y Backlog por navegación contextual; Tailwind + JS nativo en F5, Angular reservado para F8; mobile supervisión y gates, tablet operativa, web centro de control | F5, F8 |
| Persistencia de numerosas proyecciones/eventos/capacidad histórica | DB estrictamente mínima de configuración/continuidad/autorización | F1, F6 |

## Tratamiento de archivos históricos
- **openspec/specs/** contiene numerosas especificaciones de comportamiento implementado anteriormente; no se borran ni se declaran falsamente modificadas por este PR. Las disposiciones incompatibles con el nuevo contrato **no autorizan construir más funcionalidad vieja**. Su desmonte/reconciliación semántica debe suceder en los Changes F1–F6 con OpenSpec nativo y evidencias.
- **openspec/changes/**, **openspec/changes/archive/**: cambios anteriores pueden seguir presentes. No crearlos, modificarlos ni archivarlos en esta actualización; cuando se trabaje F1 se resolverán conflictos sin ejecutar simultáneamente el R01 anterior.
- **docs/backlog/MM-Rxx.md, docs/agent-capabilities/** y skills/harnesses existentes: históricos o reutilizables sujetos a inventario real; NO constituyen mandato de ejecutar Rxx, programar hooks no instalados o agregar layers nuevos.
- **Issues #15, #57, #133–#138 y #162:** inventariados y **cerrados individualmente** (no planificados de forma independiente; #138 duplicado), con comentarios motivados que enlazan las fases de destino. Los Issues permanecen consultables con todo su historial. **La referencia #169–#174 describe las seis Issues del programa original.** Las nuevas [#189](https://github.com/silverberdi/mini-me/issues/189) y [#190](https://github.com/silverberdi/mini-me/issues/190) están **disabled** y no admitidas para ejecución.
- **PR [#140](https://github.com/silverberdi/mini-me/pull/140):** cerrado **sin merge** tras revisar su diff: motor de quality hooks, analizadores de especialidades, CLI, esquema y skills. Contradice el límite de no construir un motor paralelo de calidad. Mantener el historial y aprovechar exclusivamente verificaciones concretas necesarias, si se demuestra su pertinencia dentro de F1/F3/F4, no fusionar este PR completo.
- **PR [#152](https://github.com/silverberdi/mini-me/pull/152):** cerrado **sin merge** tras revisar su diff: ruta específica de continuación AUTH_REQUIRED sobre ControlPlane, ExecutionPipeline, Orchestration y RecoveryConvergence heredados. La recuperación mínima requerida se diseñará en F3 sin trasladar automáticamente este subsistema. Historial y pruebas preservados.
- **PR [#175](https://github.com/silverberdi/mini-me/pull/175):** **PR histórico de adopción del contrato rector y seis fases**; esta descripción es un registro del momento de la versión 1.2, **no** del estado actual de PRs. El bootstrap F5 [#188](https://github.com/silverberdi/mini-me/pull/188) se trata por separado y permanece Draft hasta verificación/decisión.
- **Issue #162 (UX de cinco vistas):** cerrado como unidad de ejecución, **NO descartado como requisitos de producto**. Su documento de cinco pantallas, criterios operativos y aceptación previamente aprobados es insumo de la Fase 5 [#173](https://github.com/silverberdi/mini-me/issues/173). El refinamiento humano posterior de 2026-10-26 **resuelve la navegación** y fija cinco vistas responsivas con Dashboard/Proyectos únicamente como destinos principales. Móvil prioriza observabilidad y gates sencillos y conserva acceso a cinco pantallas; controles F7 sin API son visuales y deshabilitados en todos los dispositivos. Ver [F5_UX_CONTRATO.md](F5_UX_CONTRATO.md). No tomar el antiguo requisito de cinco botones principales o de habilitar mutaciones inexistentes como prevalente. Se dejó referencia explícita en #173.
- **Código y DB**: conservar lo útil hasta retirada segura por Change; no confundir nueva autoridad documental con migración ejecutada.

## Qué debe comprobar F1
Llamadas reales y consumidores de OpenSpecGenerator, OpenSpecSyncService, VerifyGate, SchedulerService, ExecutionPipeline y PostMergeReconciliation; tablas y migraciones que usan; compatibilidad con el contrato de seis fases; PRs borradores y worktrees históricos activos. Retirar con protección de datos, pruebas y sin crear sistema paralelo.

## Evidencia, autoridad y siguientes pasos
La actualización documental v1.3 **solo ajusta contexto y backlog**; no crea/activa ningún Change, no autoriza motores, consumo de agentes, scheduler, PR merge ni despliegue. Issues #169–#174 corresponden a la reconstrucción original; #189/#190 son evolución posterior y permanecen **disabled**. F5 y F6 deben ejecutarse efectivamente por mini me.

Si una spec histórica contradice el contrato, NO fingir que OpenSpec CLI la desactivó: documentar conflicto y resolverlo mediante el Change apropiado antes de implementar esa responsabilidad.