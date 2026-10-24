# mini me — Instrucciones de agentes (contrato rector 1.2)

**Leer primero** [docs/CONTRATO_RECTOR.md](docs/CONTRATO_RECTOR.md), [docs/BACKLOG.md](docs/BACKLOG.md) y [docs/RECONCILIACION_LEGADO.md](docs/RECONCILIACION_LEGADO.md). Luego leer el Change OpenSpec **único y autorizado** de la fase que corresponda, README y openspec/config.yaml. Otros documentos pueden reflejar decisiones HISTÓRICAS ya sustituidas; no son autoridad cuando contradicen el contrato 1.2.

## No negociable
- Seis fases exactas (F1–F6); **un Change por fase, una o múltiples specs**, jamás microchanges técnicos.
- F1 eliminar emulación OpenSpec y DB/lógica obsoleta; F2 proyectos; F3 flujo OpenSpec y revisión independiente; F4 skills base; **F5 y F6 ejecutadas por mini me**.
- mini me coordina; los agentes ejecutan los workflows oficiales propose/update/continue/apply/verify/sync/archive. NO crear Python generators, custom Markdown mergers, archive shutil, prompt substitutes ni verificadores semánticos paralelos.
- Ticket más antiguo elegible desde GitHub; no cola paralela DB, no scoring, un cambio activo por proyecto hasta sync/archive + cierre. GitHub inicial; ADO no implementado.
- Roles configurables pensamiento/ejecución/revisión independiente/respaldo; review de propuesta y código obligatorios solo para alta complejidad. Revisor de solo lectura, no certifica su propia autoría.
- Capturar preguntas originales y opciones de OpenSpec; si no hay opciones, pensamiento intenta respuesta fundamentada en contexto sin usurpar autorizaciones humanas; luego operador responde y el trabajo continúa.
- Primer PR de implementación con merge automático para baja/moderada complejidad y acuse informativo humano («Estoy enterado») para alta complejidad. PR de sync/archive documental se fusiona automáticamente. Cierre remoto de ticket únicamente tras el segundo merge. Despliegue fuera de mini me, por CI/CD del proyecto.
- POO, SOLID, DRY, KISS, YAGNI, clases pequeñas, interfaces mínimas, eliminar código/DB muerto pertinente mediante migraciones conservadoras; evidencia real E2E.
- No ejecutar acciones pagas, reiniciar scheduler, migrar/desplegar ni cerrar tickets históricos por el mero hecho de aprobar documentos.

## Orden operativo
Contrato rector → OpenSpec del Change autorizado → inventario del código/DB real → diseñar la menor solución suficiente → aplicar por skill nativa → probar resultado real → PR humano → sync/archive nativos → cierre. Conservar evidencia sin crear nueva burocracia.

## Regla permanente de aceptación de entregas
Una implementación no se declara completa por el número de tareas marcadas, la cantidad de tests aprobados o el informe de su ejecutor. Todo criterio que exija una integración real necesita evidencia observable de la invocación, su resultado y sus efectos. Las pruebas simuladas no pueden presentarse como E2E reales. La revisión independiente debe contrastar el código y la evidencia contra un SHA inmutable. Ante evidencia ausente, ambigua o fallida, se aplica fail-closed.

Los expedientes anteriores MM-Rxx y Nxx quedan como referencias históricas hasta reconciliación; el backlog vigente se limita a los Issues #169–#174.

