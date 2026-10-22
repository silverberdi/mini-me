# Definition of Ready / Done — mini me v1.2

**Autoridad:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md). DoR/DoD deben aportar evidencia, no multiplicar gates propios.

## Ready para ejecutar un Change
- Es UNA de las seis fases en el orden acordado, con issue asociado y Change OpenSpec oficial correspondiente, sin microchanges.
- Requerimiento observable, propuesta/artefactos del esquema por agente cuando aplique, scope no ambiguo.
- Repositorio y rama confiables, credenciales seguras, agente/skill real compatible y presupuesto autorizado.
- No existe otro Change activo del mismo proyecto; el operador ha autorizado iniciar la fase bajo condiciones de cuota seguras.
- Definir pruebas pertinentes, código/DB a reutilizar o eliminar y preservación de datos si corresponde.

## Done de un Change
- Comportamiento solicitado demostrado; pruebas enfocadas/integración/E2E reales conforme a la capacidad afirmada.
- Sin implementación propia que emule OpenSpec, sin nuevos estados/servicios superfluos; código muerto retirado dentro del alcance.
- Agentes verdaderamente invocados; propuesta revisada independientemente y código revisado si la política lo exige; preguntas humanas resueltas.
- PR implementación en Git con merge humano para SHA revisado; sync/archive nativos en rama nueva, PR documental autorizado y merge confirmado; ticket remoto cerrado.
- F5 y F6: **evidencia verificable de ejecución por mini me** (no mensajes manuales).
- No exigir despliegue productivo por mini me; pertenece a CI/CD externo.
- Para migraciones de DB: Alembic seguro, conservación/backup/rollback y verificación de lo retenido.

Ni tests mock PASS, ni health 200, ni un PR solamente creado prueban DONE.