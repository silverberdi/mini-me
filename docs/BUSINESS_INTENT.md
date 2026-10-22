# Intención de negocio — mini me

mini me existe para quitarle al operador la tarea de pasar requerimientos y contexto entre diferentes agentes de programación. Debe ser pequeño y útil (**una gacela, no un paquidermo**): toma tickets de su fuente externa, coordina agentes mediante workflows oficiales de OpenSpec y obtiene cambios reales listos para revisión/merge y cerrados documentalmente.

El operador no programa ni actúa como mensajero de prompts: autoriza decisiones reservadas, especialmente merge del código; el agente de pensamiento resuelve dudas contextuales cuando puede, y la UI presenta opciones reales cuando hace falta.

Una instalación personal con FastAPI, PostgreSQL mínimo y GitHub inicial. Agentes por rol y modelo configurables; independencia de revisión; POO/SOLID/DRY/KISS/YAGNI; no emular OpenSpec ni guardar otra cola de tickets; CI/CD del proyecto despliega, mini me no.

**Éxito:** ticket remoto → propose → revisión independiente de propuesta → apply → verify → revisión condicional de código → PR → merge humano → sync/archive nativos → PR documental autorizado → ticket cerrado → siguiente. Fases de reconstrucción EXACTAMENTE 6 (issues #169–#174); desde fase 5 mini me debe ejecutar su propio desarrollo.

Contrato detallado: [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md).