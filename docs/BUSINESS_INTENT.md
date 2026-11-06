# Intención de negocio — mini me

mini me existe para quitarle al operador la tarea de pasar requerimientos y contexto entre agentes de programación. Debe ser pequeño y útil: toma tickets de su fuente externa, coordina agentes mediante workflows oficiales de OpenSpec y obtiene cambios reales, verificables y cerrados documentalmente.

El operador autoriza los cambios y conserva las decisiones reservadas, especialmente las de seguridad, alcance, gasto excepcional y las autorizaciones humanas exigidas por el contrato. El agente de pensamiento resuelve dudas contextuales cuando tiene evidencia y autoridad; mini me presenta preguntas originales con su contexto cuando se necesita intervención humana.

El producto es una instalación personal con una API FastAPI, PostgreSQL limitado a configuración y continuidad necesarias, GitHub como fuente inicial de tickets y roles de agente configurables. Los agentes ejecutan OpenSpec nativo; mini me no genera artefactos semánticos ni sustituye sus workflows. El CI/CD del proyecto administra despliegues.

**Resultado esperado:** ticket remoto elegible → explore/propose → apply → verify y correcciones → revisión independiente de propuesta y código solo cuando la complejidad es alta → PR y autorización/acuse conforme a la política vigente → sync/archive nativos → cierre remoto → siguiente ticket. Cada criterio de integración requiere evidencia observable ligada a un SHA inmutable.

La política de cambios vigente es la de [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md) v2.0: un Issue corresponde a un Change OpenSpec cohesivo, con autorización del operador. Los programas F1–F8 y los Issues asociados son historia de entrega, no una secuencia de fases pendiente.
