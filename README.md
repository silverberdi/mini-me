# mini me — la gacela

mini me es una aplicación **personal y de instalación única** que coordina agentes usando los workflows **nativos de OpenSpec** para convertir tickets remotos en cambios implementados, verificados, fusionados y archivados. No programa ni recrea OpenSpec.

**Contrato rector:** [docs/CONTRATO_RECTOR.md](docs/CONTRATO_RECTOR.md) (versión 1.2).
**Backlog de reconstrucción:** [docs/BACKLOG.md](docs/BACKLOG.md).
**Reconciliación del legado:** [docs/RECONCILIACION_LEGADO.md](docs/RECONCILIACION_LEGADO.md).
**Contexto de OpenSpec:** [openspec/config.yaml](openspec/config.yaml).
**Instrucciones para agentes:** [AGENTS.md](AGENTS.md).

## Dirección vigente
GitHub Issues (inicial) → ticket más antiguo elegible → propose y revisión independiente de propuesta → apply → verify + correcciones → review de código condicional → PR → merge humano → sync/archive nativos desde rama documental nueva → PR documental autorizado → ticket cerrado → siguiente.

Los roles pensamiento, ejecución, revisión independiente y respaldo y sus modelos son configurables. La DB mantiene solo configuración y checkpoints necesarios, no la cartera de tickets. Las preguntas de OpenSpec se presentan con opciones originales o se intentan resolver con contexto sin usurpar autoridad humana.

**Una API FastAPI, arquitectura modular pequeña, POO/SOLID/DRY, KISS/YAGNI.** mini me no despliega: despliegue pertenece al CI/CD del proyecto.

## Reconstrucción: exactamente seis Changes
1. [#169](https://github.com/silverberdi/mini-me/issues/169) — depuración inicial (lógica/DB, emulación OpenSpec).
2. [#170](https://github.com/silverberdi/mini-me/issues/170) — proyectos y roles configurables.
3. [#171](https://github.com/silverberdi/mini-me/issues/171) — OpenSpec nativo, revisión y E2E real.
4. [#172](https://github.com/silverberdi/mini-me/issues/172) — skills base reutilizables.
5. [#173](https://github.com/silverberdi/mini-me/issues/173) — UI; **mini me debe ejecutar su propio Change**.
6. [#174](https://github.com/silverberdi/mini-me/issues/174) — segunda depuración; **mini me debe ejecutar su propio Change**.

Un Change por fase, con una o más especificaciones. Las specs y MM-R01–R10 anteriores son historia que se debe conciliar, no un backlog paralelo. Esta actualización de documentos NO ejecuta ninguno de los Changes.

**mini me debe ser una gacela, no un paquidermo.** El valor es un recorrido real completo, no la cantidad de código o checks.
