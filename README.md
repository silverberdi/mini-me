# mini me — la gacela

mini me es una aplicación personal de instalación única que coordina agentes usando los workflows nativos de OpenSpec para convertir tickets remotos en cambios implementados, verificados y cerrados documentalmente. No sustituye esos workflows ni programa en lugar de los agentes.

**Contrato rector:** [docs/CONTRATO_RECTOR.md](docs/CONTRATO_RECTOR.md) (versión 2.0).
**Contexto de OpenSpec:** [openspec/config.yaml](openspec/config.yaml).
**Instrucciones para agentes:** [AGENTS.md](AGENTS.md).
**Historial de entregas:** [docs/ROADMAP.md](docs/ROADMAP.md).

## Dirección vigente

GitHub Issues (fuente inicial) → Issue elegible más antiguo dentro del flujo autorizado → explore/propose nativos → apply/verify y correcciones → revisión independiente de propuesta y código solo para complejidad alta → PR según política → sync/archive nativos en rama documental nueva → PR documental → cierre remoto.

Los roles de pensamiento, ejecución, revisión independiente y respaldo son configurables. PostgreSQL conserva configuración y continuidad indispensables, no una copia de la cartera de tickets. Las decisiones reservadas y autorizaciones humanas siguen bajo control del operador. mini me no administra despliegues productivos; los realiza el CI/CD del proyecto.

## Gobierno de cambios

Un Issue corresponde a un Change OpenSpec cohesivo, con autorización del operador. No hay una secuencia fija de fases operativas. Las etiquetas F1–F10 y los Issues asociados son historia de entrega, no un backlog pendiente.

**mini me debe ser una gacela, no un paquidermo.** El valor es un recorrido real, mantenible y verificable, no la cantidad de código o checks.
