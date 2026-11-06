# Definition of Ready / Done — mini me

**Autoridad:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md) v2.0. Estos criterios orientan la evidencia y no crean una ruta paralela de autorización.

## Ready

- Hay un Issue abierto con alcance observable y el operador autorizó el Change OpenSpec correspondiente.
- Repositorio, rama, identidad y permisos son confiables; el agente y workflow real están disponibles y el gasto está dentro de política.
- No hay otro Change activo para el mismo proyecto; el alcance, riesgos, persistencia afectada y pruebas pertinentes están identificados.
- Los criterios de integración especifican qué invocación y efectos reales deben observarse.

## Done

- El comportamiento solicitado está demostrado con pruebas proporcionales al riesgo y E2E reales cuando la aceptación lo requiere.
- La propuesta y el candidato coinciden con el Issue y Change autorizados; la revisión independiente de propuesta/código se hizo cuando la complejidad es alta.
- El revisor es independiente, de solo lectura y revisó el SHA exacto; las decisiones humanas requeridas están registradas.
- La política de PR, merge de implementación, sync/archive nativos, PR documental y cierre remoto se completó con evidencia observable.
- No quedan rutas obsoletas duplicadas dentro del alcance; migraciones Alembic preservan datos e historial y tienen recuperación documentada.
- Los cambios de UI tienen validación de usuario y evidencia del candidato exacto cuando el contrato lo requiere.

Ni tests simulados, ni health 200, ni tareas marcadas ni un PR creado prueban por sí solos que el cambio esté completo. mini me no exige ni ejecuta despliegue productivo como condición de cierre.
