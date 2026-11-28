# Proposal

## Why

La proyección de autonomía de telemetría colapsa actualmente un Change completo a 0% cuando tuvo cualquier intervención humana, aunque esa intervención haya sido una autorización breve de gobernanza y el resto de las etapas se haya ejecutado autónomamente. Esto distorsiona la comparación histórica del Dashboard y hace que la autonomía real de construcción no sea observable; el cambio es necesario ahora para corregir la métrica sin perder la distinción entre autorización de alcance, bloqueo técnico y recuperación autónoma.

## What Changes

- Cambiar la dimensión `autonomy` de una clasificación binaria por Change a una medición proporcional por etapas recorridas, usando evidencia durable de etapas y gates; el resultado deberá conservar una semántica acotada y verificable.
- Distinguir explícitamente un gate humano legítimo de gobernanza/autorización de alcance de una intervención requerida por bloqueo o falla técnica, sin contar ambos como el mismo resultado.
- Mantener separadas las categorías de ejecución limpia, recuperación autónoma y asistencia/bloqueo técnico, y exponer la evidencia de etapas considerada en la proyección.
- Reproyectar de forma idempotente los runs históricos disponibles para todos los proyectos, incluyendo picas-fijas, mini-me, multiplo y boxio cuando sus datos estén almacenados, sin borrar históricos ni requerir migraciones destructivas.
- Actualizar la lectura del Dashboard para que consuma inmediatamente la proyección recalculada y mantenga los estados explícitos de no-data/no-verificado.
- Retirar la lógica binaria sustituida y sus expectativas de 0/100 por Change, conservando las pruebas de intervención, recuperación autónoma, evidencia ambigua y pureza de consultas que sigan siendo válidas.

## Capabilities

### New Capabilities

- `historical-telemetry-reprojection`: Reproyección idempotente y no destructiva de observaciones históricas de telemetría a partir de evidencia PostgreSQL existente.

### Modified Capabilities

- `temporal-multiseries-telemetry`: Modifica el cálculo y la clasificación de la dimensión de autonomía para hacerla proporcional por etapas y distinguir gobernanza de bloqueo técnico, manteniendo la proyección temporal, sus controles y sus estados de evidencia.

## Impact

- Backend: `src/minime/services/temporal_multiseries_telemetry_service.py`, servicios/repositorios de runs y eventos de etapas, y el endpoint de lectura del Dashboard.
- Persistencia: lectura de runs, eventos, gates/acciones y demás evidencia durable existente; cualquier persistencia auxiliar deberá usar Alembic y preservar todos los históricos.
- Frontend: modelos, resumen de resultados y gráfica temporal del Dashboard, únicamente donde sea necesario para representar el valor proporcional y la distinción de outcomes.
- Pruebas: `tests/test_temporal_multiseries_telemetry.py` y pruebas E2E específicas del Dashboard; las verificaciones deberán invocar la ruta real de proyección y demostrar el efecto sobre datos históricos.
- No incluye despliegue productivo, cambio de proveedor de datos, nueva cola de telemetría ni migración destructiva.
