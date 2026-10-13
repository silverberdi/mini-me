# mini me — roadmap por capacidades demostradas

## Autoridad y criterio

El roadmap anterior (stages 001–022) queda como **historial de trabajo técnico**, consultable en Git, PR, specs archivadas y evidencias previas. Los rótulos históricos `DELIVERED` no garantizan por sí solos un ciclo E2E productivo. La referencia vigente de **trabajo por entregar** es [BACKLOG](BACKLOG.md), cuyas fichas trazan valor, escenarios y pruebas.

Un stage/Change avanza solamente cuando produce utilidad observable, cumple los E2E correspondientes (incluida verificación post-despliegue) y satisface [CHANGE_DELIVERY_CONTRACT](CHANGE_DELIVERY_CONTRACT.md). No medir avance por número de commits, clases, pruebas unitarias o Changes archivados.

## Secuencia vigente

| Hito | Cambios | Capacidad demostrable |
|---|---|---|
| A — Primer software real | R01 | Agente real + OpenSpec + agente revisor + PR sin mini me programando |
| B — Del Issue al PR | R02, R03 | Preparación inteligente y cola autónoma hasta revisión |
| C — Entrega y continuidad | R04, R05 | Cierre real nativo y recuperación segura ante interrupciones/cuotas |
| D — Calidad y control operativo | R06, R07 | Capabilities contextuales efectivas y UI de atención humana |
| E — Autonomía transferible | R08, R09 | Segundo repositorio y evolución gobernada de capacidades |
| F — Autodesarrollo | R10 | mini me desarrolla mini me con human merge y post-deploy E2E |

**Solo R01 es elegible para ser el siguiente Change activo.** Los restantes son backlog; no crear directorios de OpenSpec para ellos antes de autorizar `propose` del Change correspondiente.

## Restricciones de cada hito

- **A:** contiene adaptador real, selección de agente y reviewer, aislamiento, preflight de cuota, checks, E2E con cambios verdaderos y PR. No bloquear A por una futura plataforma de plugins.
- **B:** GitHub y generación de contratos dependen de agent-led OpenSpec; no generar specs determinísticas para “pasar el gate”.
- **C:** operaciones GitHub/DB/Git son determinísticas/durables; el contenido semántico de OpenSpec se delega a workflows nativos.
- **D:** reutilizar PR #140 y superficie PWA cuando cumplan contrato; no construir una biblioteca genérica sin consumo probado.
- **E:** segundo repositorio real prueba ausencia de supuestos hardcoded; expandir capacidades solo por necesidad demostrada.
- **F:** autonomía significa crear PRs bajo políticas, no auto-merge ni auto-authorize cuotas, secrets o despliegues peligrosos.

## Regla para cualquier cambio de orden

Exigir actualización de su ficha de backlog mediante `update`/propuesta gobernada, análisis de dependencia y prueba de que el nuevo orden entrega **más valor usable** sin saltarse seguridad/E2E. No volver a numerar el historial ni simular que los nuevos R01–R10 ya fueron implementados.
