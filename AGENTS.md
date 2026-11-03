# mini me — Instrucciones de agentes (contrato rector 2.0)

**Leer primero** [docs/CONTRATO_RECTOR.md](docs/CONTRATO_RECTOR.md) y [docs/RECONCILIACION_LEGADO.md](docs/RECONCILIACION_LEGADO.md). Luego leer el Change OpenSpec del Issue autorizado, README y openspec/config.yaml. Otros documentos pueden reflejar decisiones HISTÓRICAS ya sustituidas; no son autoridad cuando contradicen el contrato 2.0.

## No negociable
- Un Issue = un Change OpenSpec de alcance cohesivo; jamás microchanges técnicos ni agrupación de Issues independientes.
- mini me coordina; los agentes ejecutan los workflows oficiales propose/update/continue/apply/verify/sync/archive. NO crear Python generators, custom Markdown mergers, archive shutil, prompt substitutes ni verificadores semánticos paralelos.
- Ticket más antiguo elegible desde GitHub; no cola paralela DB, no scoring, un cambio activo por proyecto hasta sync/archive + cierre. GitHub inicial; ADO no implementado.
- Roles configurables pensamiento/ejecución/revisión independiente/respaldo; review de propuesta y código obligatorios solo para alta complejidad. Revisor de solo lectura, no certifica su propia autoría.
- Apply con recuperación guiada: ante un Apply parcial, reanudar sobre el mismo candidato con contexto correctivo basado en evidencia (Git/pruebas, no el relato del agente); límite por falta de progreso + tope duro; fail-closed ante regresión.
- La revisión independiente converge: defectos sustantivos sobre artefactos completos, sin re-flag ni peticiones de formato.
- Capturar preguntas originales y opciones de OpenSpec; si no hay opciones, pensamiento intenta respuesta fundamentada en contexto sin usurpar autorizaciones humanas; luego operador responde y el trabajo continúa. El gate humano muestra siempre la pregunta vigente con opciones.
- Higiene de workspace y re-ejecución idempotente: al completar o cancelar un run, limpiar worktree y registro de propiedad; observar el estado antes de repetir una etapa.
- Primer PR de implementación con merge automático para baja/moderada complejidad y acuse informativo humano («Estoy enterado») para alta complejidad. PR de sync/archive documental se fusiona automáticamente. Cierre remoto de ticket únicamente tras el segundo merge. Despliegue fuera de mini me, por CI/CD del proyecto.
- POO, SOLID, DRY, KISS, YAGNI, clases pequeñas, interfaces mínimas, eliminar código/DB muerto pertinente mediante migraciones conservadoras; evidencia real E2E.
- No ejecutar acciones pagas, reiniciar scheduler, migrar/desplegar ni cerrar tickets históricos por el mero hecho de aprobar documentos.

## Orden operativo
Contrato rector → OpenSpec del Change autorizado → inventario del código/DB real → diseñar la menor solución suficiente → aplicar por skill nativa → probar resultado real → PR humano → sync/archive nativos → cierre. Conservar evidencia sin crear nueva burocracia.

## Regla permanente de aceptación de entregas
Una implementación no se declara completa por el número de tareas marcadas, la cantidad de tests aprobados o el informe de su ejecutor. Todo criterio que exija una integración real necesita evidencia observable de la invocación, su resultado y sus efectos. Las pruebas simuladas no pueden presentarse como E2E reales. La revisión independiente debe contrastar el código y la evidencia contra un SHA inmutable. Ante evidencia ausente, ambigua o fallida, se aplica fail-closed.

Los expedientes anteriores MM-Rxx y Nxx quedan como referencias históricas hasta reconciliación.
