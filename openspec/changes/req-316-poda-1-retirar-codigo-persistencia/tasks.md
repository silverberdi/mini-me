## 1. Auditoría y censo de superficies UI

- [ ] 1.1 Ejecutar el censo estático de llamadas HTTP desde `frontend/src/app/` hacia la API FastAPI y registrar el mapa de endpoints consumidos.
- [ ] 1.2 Auditar rutas, controladores y servicios en `src/minime/` para identificar candidatos con cero consumidores en la UI y flujos autorizados.
- [ ] 1.3 Auditar modelos SQLAlchemy y tablas PostgreSQL para identificar tablas huérfanas (logs de Jobs, hechos métricos no consumidos, restos de previews).
- [ ] 1.4 Vincular la evidencia del resultado de la suite de pruebas base previa ejecutada por el operador sobre el SHA de partida.
- [ ] 1.5 Crear la estructura del documento de inventario histórico `docs/evidence/poda-1-inventario-features-retiradas.md`.

## 2. Poda de backend y modelos huérfanos

- [ ] 2.1 Retirar rutas y controladores sin consumidor en `src/minime/api/` y limpiar su registro en el router principal.
- [ ] 2.2 Retirar servicios huérfanos o funciones no alcanzables en `src/minime/services/`.
- [ ] 2.3 Retirar modelos SQLAlchemy desincorporados en `src/minime/models/` y actualizar los metadatos canónicos de la aplicación.
- [ ] 2.4 Retirar configuraciones y dependencias que queden sin efecto tras la poda.

## 3. Persistencia y migración Alembic

- [ ] 3.1 Diseñar y generar la nueva revisión de migración Alembic con funciones simétricas de `upgrade()` y `downgrade()`.
- [ ] 3.2 Verificar en base de prueba disposable la aplicación de la migración y la capacidad de rollback exitoso.
- [ ] 3.3 Confirmar que la verificación de preflight de invariantes de esquema (`SCHEMA_INVARIANT_VIOLATION`) pasa en verde con los nuevos metadatos.

## 4. Depuración de pruebas obsoletas

- [ ] 4.1 Identificar y eliminar archivos y casos de prueba en `tests/` que correspondían exclusivamente a rutas, servicios y modelos retirados.
- [ ] 4.2 Preservar intactas todas las pruebas unitarias, de integración y E2E que respaldan los flujos y datos de la UI vigente.

## 5. Verificación y evidencia observable

- [ ] 5.1 Ejecutar la suite completa retenida en un entorno PostgreSQL desechable aislado asegurando exit code 0.
- [ ] 5.2 Comparar los resultados con la línea base inmutable previa del operador demostrando cero regresiones en los flujos activos.
- [ ] 5.3 Consolidar en `docs/evidence/poda-1-inventario-features-retiradas.md` el inventario exhaustivo de cada feature retirada con su propósito original y su SHA de referencia para recuperación futura.
- [ ] 5.4 Documentar la evidencia final de retiro y cero consumidores en el informe del Change.
