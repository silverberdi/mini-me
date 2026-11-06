# Aceptación del sistema — mini me

**Autoridad:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md) v2.0 y el Change OpenSpec del Issue autorizado.

## Recorrido funcional

Proyecto configurado → admisión autorizada del Issue remoto elegible más antiguo → Explore/Propose nativos → revisión independiente de propuesta solo para complejidad alta → Apply con cambio real y pruebas → Verify por el ejecutor y correcciones acotadas → revisión independiente del código solo para complejidad alta → PR y política de autorización aplicable → rama documental nueva → Sync/Archive nativos → PR documental fusionado → cierre remoto del Issue.

Cada criterio de integración real exige evidencia de invocación, resultado y efecto, ligada al repositorio/candidato/SHA correctos. El test unitario, mock, workflow exitoso sin efecto verificable o HTTP 200 no sustituyen esa evidencia.

## Clasificación de evidencia

- **Técnica:** pruebas unitarias e integración para lógica local y contratos.
- **Integración:** proveedor/Git/OpenSpec invocados con resultado observable cuando el Change depende de ellos.
- **E2E:** agente y workflow reales, efectos externos comprobados y candidato identificado.
- **Validación de UI:** escenarios humanos explícitos para cambios de UI cuando aplique, sobre el candidato exacto.

El despliegue productivo pertenece al CI/CD del proyecto. `DEPLOYED_VERIFIED` no es un gate universal de mini me; la aceptación de cada Change sigue los criterios del contrato y su Change autorizado.

## Pruebas de fallos según riesgo

Considerar autenticación, cuota/capacidad, timeout, salida malformada, interrupción, reentrada, duplicación de side effects, worktree existente, remote mismatch, candidato cambiado después de review/validación, fallo de proveedor y espera de decisión humana. La suite concreta se determina en el Change; esta lista no obliga a añadir todos los casos a cada cambio.

## Seguridad y operación

- No versionar secretos ni transmitir contenido del repositorio a proveedores no autorizados.
- Revisión read-only solo para complejidad alta; nadie certifica su propia autoría.
- No emular OpenSpec ni mantener una ruta de autoridad duplicada.
- No consumir cuota, iniciar trabajo, desplegar ni modificar políticas sin autorización aplicable.
- Mantener los datos operativos y transiciones necesarios de forma transaccional; las migraciones deben conservar datos y contemplar recuperación.

La cantidad de tareas completas no equivale al resultado; la evidencia del comportamiento y sus efectos determina la aceptación.
