# Proposal

## Why

mini me acumuló rutas, controladores, servicios, modelos, pruebas y tablas de esquemas o experimentos históricos que no corresponden a ninguna acción ni dato mostrado en la UI vigente. El [Contrato Rector v2.0](docs/CONTRATO_RECTOR.md) (§1, §7) establece el principio de «la gacela, no el paquidermo»: la UI actual define el perímetro funcional legítimo del sistema, y la documentación o el código heredado no justifican por sí solos conservar superficies en runtime o persistencia.

## What Changes

- Identificar y auditar la trazabilidad de cada ruta FastAPI, servicio, modelo SQLAlchemy y tabla PostgreSQL hacia un componente, acción o dato de la UI actual (Dashboard, Trabajo, Trabajo actual, Proyectos, Backlog y Administración de modelos).
- Retirar del código fuente todas las rutas, controladores y servicios huérfanos que carecen de consumidor activo en la UI o en los flujos de coordinación autorizados.
- Retirar modelos y tablas huérfanas en desuso (incluyendo logs de Jobs obsoletos, hechos métricos no leídos, restos de validaciones o previews heredadas y configuraciones sin efecto).
- Generar migraciones conservadoras con Alembic para desincorporar tablas o columnas sin uso, garantizando capacidad de rollback y preservación/exportación de históricos donde corresponda, sin alterar la base de datos de producción.
- Eliminar concurrentemente las pruebas obsoletas que cubrían exclusivamente las superficies retiradas, sin suprimir pruebas de flujos vigentes.
- Generar un documento de inventario histórico (`docs/evidence/poda-1-inventario-features-retiradas.md`) que registre detalladamente cada feature, ruta, servicio, modelo y tabla desincorporada, su propósito original y los SHAs/commits de referencia en Git para facilitar su consulta o recuperación futura si se requiere.
- Validar la ausencia de regresiones comparando el resultado de la suite de pruebas del candidato contra la ejecución de línea base realizada por el operador sobre el SHA previo.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `delivery-quality-and-safe-retirement`: la retirada segura de código y persistencia queda delimitada estrictamente por la trazabilidad a las 5 vistas de la UI vigente y la administración de modelos; exige evidencia de cero consumidores y validación del candidato frente a la línea base inmutable previa del operador.
- `postgres-durable-state`: la persistencia retenida se limita exclusivamente al estado mínimo necesario para sostener los flujos de la UI vigente y la coordinación autorizada; la desincorporación de tablas o columnas requiere migraciones Alembic reversibles sin afectar entornos productivos.

## Impact

- Código backend: rutas en `src/minime/api/`, servicios en `src/minime/services/`, modelos en `src/minime/models/` y esquemas huérfanos.
- Persistencia: nuevas revisiones de Alembic en `alembic/versions/` para retirar de forma ordenada tablas/columnas huérfanas identificadas.
- Pruebas: depuración en `tests/` eliminando pruebas de endpoints y servicios retirados.
- Superficies preservadas intactas: API activa de proyectos, requests, autenticación/sesión, health/status, proveedores y modelos, coordinación nativa OpenSpec y la PWA Angular activa.
- Despliegue y base productiva: estrictamente fuera de alcance; ninguna acción modifica producción ni despliega servicios.
