# Reconciliación de documentación, specs y backlog heredados

**Autoridad nueva:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md) v1.2 y [BACKLOG.md](BACKLOG.md). Este documento NO prueba que las implementaciones antiguas ya hayan sido retiradas.

## Cambio de dirección
La historia 001–022, el backlog de recuperación MM-R01–MM-R10, los tickets N01–N05 y los dossiers respectivos describen trabajo anterior con componentes y políticas que el nuevo contrato puede sustituir. Permanece como evidencia/historia técnica. **No debe tratarse como una segunda ruta vigente de ejecución.** No borrar Issues/PR, worktrees o datos operativos mediante este ajuste documental.

## Contradicciones explícitas
| Tema heredado | Dirección sustituida por contrato 1.2 | Fase responsable |
| --- | --- | --- |
| Plan MM-R01–R10 y prioridad de stages técnicos | Seis fases exactas, un Change por fase, sin subdivisión | F1–F6 |
| Scheduler con scoring/aging, gates y backlog DB | Ticket remoto más antiguo elegible; un activo por proyecto | F1, F3, F6 |
| Codex/AGY/DeepSeek roles preasignados en core | Cuatro roles/modelos configurables, independientes | F2, F3 |
| OpenSpecGenerator y creación propia de specs | Agent-side native propose/update | F1 |
| Python OpenSpecSyncService y archive por movimiento de carpetas | Agent-side native sync/archive | F1, F3 |
| Verificadores semánticos sustitutos de workflow verify | Agent-side native verify + tests pertinentes | F1, F3 |
| Revisión código siempre obligatoria por DeepSeek | Propuesta siempre revisada; revisión de código condicional según política; revisor distinto/solo lectura | F2, F3 |
| Merge solo fuera de UI / segunda publicación sin contrato | Merge implementación autorizado por humano en UI; PR documental mergeable automáticamente si Git lo permite | F3, F5 |
| mini me responsable de despliegue/productivo/postdeploy | Despliegue responsabilidad exclusiva de CI/CD de cada proyecto | F1, F3, F6 |
| Intervención humana como bloqueo bruto | Opciones originales; pensamiento contextual si no hay opciones, humano cuando sea necesario | F3, F5 |
| UI histórica centrada en pipeline viejo | Mobile observación, Tablet operativa, Web control center, bandeja humana | F5 |
| Persistencia de numerosas proyecciones/eventos/capacidad histórica | DB estrictamente mínima de configuración/continuidad/autorización | F1, F6 |

## Tratamiento de archivos históricos
- **openspec/specs/** contiene numerosas especificaciones de comportamiento implementado anteriormente; no se borran ni se declaran falsamente modificadas por este PR. Las disposiciones incompatibles con el nuevo contrato **no autorizan construir más funcionalidad vieja**. Su desmonte/reconciliación semántica debe suceder en los Changes F1–F6 con OpenSpec nativo y evidencias.
- **openspec/changes/**, **openspec/changes/archive/**: cambios anteriores pueden seguir presentes. No crearlos, modificarlos ni archivarlos en esta actualización; cuando se trabaje F1 se resolverán conflictos sin ejecutar simultáneamente el R01 anterior.
- **docs/backlog/MM-Rxx.md, docs/agent-capabilities/** y skills/harnesses existentes: históricos o reutilizables sujetos a inventario real; NO constituyen mandato de ejecutar Rxx, programar hooks no instalados o agregar layers nuevos.
- **Issues #15, #57, #133–#138, #162** y PR antiguos: preservar el historial; NO cerrar ni migrar por lote. Su contenido solo vuelve al plan mediante decisión explícita vinculada a una de las seis fases.
- **Código y DB**: conservar lo útil hasta retirada segura por Change; no confundir nueva autoridad documental con migración ejecutada.

## Qué debe comprobar F1
Llamadas reales y consumidores de OpenSpecGenerator, OpenSpecSyncService, VerifyGate, SchedulerService, ExecutionPipeline y PostMergeReconciliation; tablas y migraciones que usan; compatibilidad con el contrato de seis fases; PRs borradores y worktrees históricos activos. Retirar con protección de datos, pruebas y sin crear sistema paralelo.

## Evidencia, autoridad y siguientes pasos
Este PR actualiza **contexto**, no crea ninguno de los seis Changes OpenSpec ni marca fases implementadas. La aprobación será la autoridad para redactar sucesivamente cada Change, con una o varias specs. GitHub Issues #169–#174 son únicos tickets de la nueva reconstrucción; las fases 5 y 6 deben ejecutarse por mini me.

Si una spec histórica contradice el contrato, NO fingir que OpenSpec CLI la desactivó: documentar conflicto y resolverlo mediante el Change apropiado antes de implementar esa responsabilidad.