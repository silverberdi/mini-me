# Backlog vigente — Reconstrucción gacela de mini me

**Autoridad:** docs/CONTRATO_RECTOR.md (v1.2). **ÚNICO PLAN ACTIVO: 6 fases = 6 Changes OpenSpec.**
Este documento y los Issues son planificación. Ni su creación ni la aprobación documental ejecutan agentes, migraciones, scheduler, despliegue o merge de código.

| Orden | Issue GitHub | Change planificado (NO creado) | Resultado verificable | Ejecutor de la fase |
| --- | --- | --- | --- | --- |
| 1 | [#169](https://github.com/silverberdi/mini-me/issues/169) | gacela-01-depuracion-inicial | Eliminar emulación OpenSpec, lógica y DB obsoletas sin romper núcleo útil | Agentes externos |
| 2 | [#170](https://github.com/silverberdi/mini-me/issues/170) | gacela-02-proyectos | Configurar proyectos, roles/modelos/contexto y GitHub inicial | Agentes externos |
| 3 | [#171](https://github.com/silverberdi/mini-me/issues/171) | gacela-03-openspec-y-revision | E2E real ticket → explore/propose → review (alta) → apply/pruebas → verify por ejecutor → review (alta) → PR1 diferenciado → sync/archive → PR2 auto-merge → cierre | Agentes externos |
| 4 | [#172](https://github.com/silverberdi/mini-me/issues/172) | gacela-04-skills-base | Skills mínimas reutilizables seleccionables y vinculadas | Agentes externos |
| 5 | [#173](https://github.com/silverberdi/mini-me/issues/173) | gacela-05-ui-self-hosted | UI móvil/tablet/web diseñada y desarrollada por mini me sobre sí mismo | **mini me** |
| 6 | [#174](https://github.com/silverberdi/mini-me/issues/174) | gacela-06-depuracion-final | Eliminar código/DB obsoleto residual; pruebas y cierre ejecutados por mini me | **mini me** |

## Reglas de admisión y desarrollo
1. No abrir más Changes para dividir estas fases. Cada Change puede tener MUCHAS specs y tareas de implementación, pruebas, migraciones y limpieza.
2. Solo después de cerrar la fase anterior puede ejecutarse la siguiente. No arrancar automáticamente por aprobar esta planificación.
3. Un ticket activo por proyecto; fuente de tickets remota y más antigua elegible, sin cola DB ni algoritmo de prioridad.
4. Revisión independiente de propuesta y código obligatorias solo para alta complejidad. Merge diferenciado para primer PR (automático baja/mod, acuse informativo alta); segundo PR documental con merge automático; cierre remoto de ticket únicamente tras el segundo merge.
5. Fase 3 debe probar recorrido funcional real; F5 y F6 deben ser efectivamente ejecutadas POR mini me, no mediante transferencia manual de prompts.
6. POO, SOLID, DRY, KISS, YAGNI; reducción de servicios/estados/DB, no renombrado de complejidad.

## Qué ocurre con el backlog anterior
Los dossiers [docs/backlog/MM-Rxx.md](backlog/) y PR históricos siguen siendo referencias, **no tickets ejecutables**. Tras inspeccionar su alcance y archivos, se **cerraron sin merge los PR #140 y #152**, con comentarios de cierre: el #140 introducía un motor paralelo de quality hooks; el #152 ampliaba la recuperación del orquestador heredado. Su historial y pruebas continúan consultables y solo se reutilizará material pertinente dentro de una de las seis fases. **El único PR abierto es #175**, correspondiente al contrato y planificación. Tras revisar individualmente los nueve Issues heredados abiertos, se cerraron **#15, #57, #133–#138 y #162** como no planificados por separado (el duplicado #138 se marcó como duplicado). Se añadieron comentarios de cierre con la fase responsable o el motivo de exclusión. No se borró su historial. Los **únicos seis tickets abiertos para desarrollar** son #169–#174. El Issue [#162](https://github.com/silverberdi/mini-me/issues/162) conserva requisitos UX anteriormente aprobados, que se incorporan como insumo de #173 y deben conciliarse con el contrato rector antes de APPLY. No utilizar MM-R01–R10 como plan paralelo.

La fuente de tickets real para el futuro ciclo de mini me seguirá siendo GitHub; estos seis Issues son los requerimientos de esta reconstrucción. La prioridad es **fecha remota** (para proyectos activos) y **orden contractual de fases** (durante la reconstrucción), no puntajes.

Véase [RECONCILIACION_LEGADO.md](RECONCILIACION_LEGADO.md).