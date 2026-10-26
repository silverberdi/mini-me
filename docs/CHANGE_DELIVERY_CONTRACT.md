# Contrato de entrega por Change — mini me

**Prevalece:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md) v1.3. Seis Changes del programa original de reconstrucción F1–F6, uno por fase; F7/F8 son evolución **disabled** que requieren autorización y Change propio solo cuando corresponda. Varias specs pueden existir en un Change. No subdividir para entregar microcorrecciones.

## Antes de proponer
- Leer contrato, Issue de fase autorizado (F1–F6 #169–#174; futuros F7 #189/F8 #190 **solo cuando se habiliten expresamente**), [F5_UX_CONTRATO.md](F5_UX_CONTRATO.md) si se trabaja F5, contexto openspec/config.yaml, AGENTS.md y código/DB real.
- Hacer censo de componentes/consumidores ya existentes antes de decidir REUSE / REPLACE / REMOVE; evitar reconstruir herramientas o introducir infraestructura no necesaria.
- Proposal: necesidad, actor, resultado verificable, alcance, no-objetivos, riesgos y fase; design: responsables/contratos concretos, riesgos de migración, limitación de gasto, plan de pruebas; specs: comportamientos observables; tasks: trabajo ordenado incluyendo eliminación de código/DB muerto.
- No inventar decisiones de producto ni ampliar fases. F5 solo desarrolla interfaz y capacidades backend existentes; controles de operaciones F7 sin autoridad quedan visibles pero deshabilitados. F8 migra frontend a Angular, no se anticipa en F5.

## Durante Apply y Verify
- ÚNICAMENTE workflow nativo OpenSpec del agente. Propuesta/revisión/apply/verify/sync/archive no tienen versión propia en mini me.
- Pruebas pertinentes unitarias + integración y E2E con agentes reales cuando se afirme capacidad de agentes. No convertir health 200/mocks en entrega.
- Reviewer independiente no edita el candidato que revisa; hallazgos devuelven a autor. Límite de correcciones para evitar loop pagado infinito.
- No duplicar verificadores o mantener implementación vieja por compatibilidad vacía.
- Preguntas OpenSpec: capturar opción original, resolución contextual autorizada cuando no haya opciones, intervención humana real cuando sea precisa.

## Publicación
- Un PR de implementación, autorización humana vinculada a SHA, merge por Git permitido.
- Tras merge, nuevo branch desde main, agente ejecuta sync/archive nativos, PR documental de merge únicamente autorizado por reglas Git; luego cierre ticket.
- No desplegar aplicaciones por mini me. Pruebas antes del merge y previews de UI si aplican.
- No anunciar fase concluida hasta aceptación funcional y cierre documental; F5/F6 incluyen evidencia de ejecución POR mini me.

## Migraciones y retiro
- Retirar writers, callers, configuración, pruebas exclusivamente muertas y tablas dentro de la fase asignada.
- Migraciones Alembic de DB con evaluación de datos, reversión y pruebas; NO eliminar datos a ciegas.
- Seguridad, aislamiento repo, identidad del candidato, presupuesto y decisiones humanas siguen vigentes sin construir un motor de gates superpuestos.

## Secuencia
Ver Issues F1–F6 #169–#174, futuras fases F7 [#189](https://github.com/silverberdi/mini-me/issues/189) y F8 [#190](https://github.com/silverberdi/mini-me/issues/190) **disabled**, [BACKLOG.md](BACKLOG.md) y [F5_UX_CONTRATO.md](F5_UX_CONTRATO.md). Un Issue planificado/deshabilitado no es autorización de crear Change, consumir modelos, activar scheduler ni desplegar. R01–R10 son historia, no Changes autorizados por esta dirección.