# Decisiones canónicas — mini me

**Autoridad superior:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md) v2.0. Este resumen no crea autorizaciones ni sustituye al Issue y Change OpenSpec del trabajo actual.

1. Instalación personal única: una API FastAPI, PostgreSQL solo para configuración y continuidad necesarias, UI consumidora de la API.
2. Los agentes ejecutan los workflows oficiales de OpenSpec. mini me no genera propuestas, implementa cambios de producto ni emula verify, sync o archive.
3. GitHub Issues es la fuente inicial de tickets; Git/PR y tickets tienen contratos separados. No mantener una cola duplicada en PostgreSQL.
4. Los perfiles de pensamiento, ejecución, revisión independiente y respaldo son configurables por proyecto, sujetos a compatibilidad y autorización de gasto.
5. Seleccionar el ticket elegible más antiguo al admitir trabajo autorizado; mantener como máximo un Change activo por proyecto y no saltar silenciosamente los bloqueos.
6. La revisión independiente de propuesta y código se hace únicamente para complejidad alta. El revisor es distinto del autor, de solo lectura y revisa el candidato exacto.
7. Apply se recupera sobre el mismo Change/candidato con contexto correctivo basado en evidencia; se detiene ante regresión o identidad ambigua.
8. Mostrar literalmente las preguntas y opciones de OpenSpec. Si no hay opciones, pensamiento puede resolver solo lo que el contexto y su autoridad permiten; las decisiones reservadas permanecen con el operador.
9. PR1 sigue la política de merge del contrato: merge automático en complejidad baja/moderada y acuse humano informativo para alta; PR documental y cierre de Issue después del sync/archive nativo.
10. Persistir lo necesario para continuidad, idempotencia, decisiones y gasto autorizado; preservar el historial externo en sus fuentes de autoridad.
11. mini me no administra despliegues productivos; cada proyecto los realiza mediante su propio CI/CD.
12. Mantener POO, SOLID, DRY, KISS y YAGNI; cada servicio, tabla, estado o dependencia debe responder a una necesidad vigente demostrable.

Las fases F1–F8 e Issues #169–#190 citados en documentos históricos registran entregas pasadas. El trabajo vigente se rige por Issues abiertos y autorización expresa conforme al contrato v2.0.
