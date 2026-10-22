# Decisiones canónicas vigentes — mini me (21-10-2026)

**Autoridad superior:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md) v1.2. Este documento reemplaza la antigua dirección MM-R01–R10, las reglas particulares para proveedores permanentes y el postdeploy dentro de mini me. Los cambios históricos siguen en Git como evidencia, NO como política actual.

1. Producto personal e instalación única; **gacela, no paquidermo**. Una API FastAPI, arquitectura Python POO y SOLID/DRY/KISS/YAGNI, PostgreSQL mínimo.
2. mini me coordina y observa; **agentes ejecutan workflows nativos OpenSpec**; prohibido que mini me genere propuestas, implemente, verifique semánticamente, sincronice o archive con lógica propia sustituta.
3. Proyectos configuran proveedor de tickets (GitHub ahora; ADO futuro solo con necesidad), proveedor Git/PR aparte, agentes/modelos de pensamiento, ejecución, revisión independiente y respaldo, skills preexistentes y límites.
4. Esfuerzo por defecto medio en propuesta, apply, verify y review; más bajo compatible en sync/archive. No modelos fijos a rol de por vida ni rutas específicas impuestas por el núcleo.
5. Al activar proyecto consultar fuente de tickets directamente; iniciar ticket elegible más antiguo con desempate por ID; uno activo por proyecto hasta cierre documental; no backlog duplicado en DB ni scoring.
6. Propose/Review propuesta (obligatoria) → Apply → Verify/corrección → revisión de código (condicional por política) → PR → merge humano → **nueva rama desde main** → sync/archive nativos → PR documental de merge automatizable solo con autorización/protección → ticket cerrado → siguiente.
7. El revisor independiente es **read-only**, distinto de autores del candidato. Retroalimentación va a ejecutor/pensamiento, nunca al revisor para reescribir lo que certifica. Ciclos de corrección limitados.
8. Cuando OpenSpec exige intervención: capturar mensaje/opciones; mostrar opciones explícitas al operador; sin opciones, pensamiento resuelve desde contexto solo si posee información+autoridad; si no, presentar pregunta, opciones del agente distinguidas y esperar respuesta. No autoautorizar merges, seguridad ni gastos excepcionales.
9. Humano autoriza merge de implementación ligado a PR/SHA, cambios materiales, excepciones de seguridad y presupuesto. Secretos en host, jamás logs/Git.
10. Solo configuración/checkpoints/idempotencia/decisiones/uso indispensable en PostgreSQL; tickets en remoto, OpenSpec en repo, código y commits en Git. No despliegues productivos; CI/CD de cada proyecto se ocupa.
11. Seis fases exactas, un Change por fase con múltiples specs permitidas; F1 limpiar, F2 proyectos, F3 ciclo real, F4 skills, **F5 UI ejecutada por mini me**, **F6 depuración ejecutada por mini me**. Issues #169–#174.
12. No confundir documentación/PR/planning con capacidad implementada. Conservar pruebas E2E reales, datos y estabilidad durante migración. No activar scheduler ni consumir cuotas por aprobar contexto.

Para contenido completo, límites y criterios de aceptación, consultar exclusivamente el contrato rector y el Change autorizado de la fase. La documentación previa incompatible queda documentada en [RECONCILIACION_LEGADO.md](RECONCILIACION_LEGADO.md).