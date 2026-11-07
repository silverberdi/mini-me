# Technical Design: PODA 1 — Retiro de código y persistencia huérfana

## Context

mini me opera bajo el Contrato Rector v2.0 como una aplicación personal única con backend FastAPI modular, base de datos PostgreSQL y frontend Angular PWA. Las superficies legítimas de la UI están concentradas en cinco pantallas principales (Dashboard, Trabajo, Trabajo actual, Proyectos, Backlog) y la vista de Administración de modelos.

A lo largo de iteraciones previas, se acumularon modelos, rutas API, servicios, tablas de métricas/jobs y pruebas asociadas a experimentos o contratos históricos que ya no tienen consumidores activos en la UI. Este diseño define el método de auditoría, trazabilidad y desincorporación segura.

## Goals / Non-Goals

**Goals:**
- Trazar de manera exhaustiva las llamadas HTTP desde el frontend Angular (`frontend/src/app/`) hacia la API FastAPI (`src/minime/api/`), identificando con precisión las rutas en uso.
- Identificar y retirar rutas, servicios y modelos SQLAlchemy que presenten cero consumidores activos en la UI y en la orquestación autorizada.
- Desincorporar tablas y columnas huérfanas mediante migraciones Alembic reversibles con capacidad explícita de rollback (`downgrade`).
- Retirar las pruebas obsoletas que cubren exclusivamente código o endpoints eliminados, preservando todas las pruebas de flujos vigentes.
- Validar el resultado final contra la línea base de pruebas ejecutada previamente por el operador sobre el SHA inmutable de referencia.

**Non-Goals:**
- No realizar cambios visuales, de maquetación, navegación ni lógica en el frontend Angular.
- No introducir nuevas características, campos adicionales ni refactorizaciones de arquitectura no solicitadas.
- No modificar esquemas ni datos en entornos de producción.
- No reescribir la infraestructura de CI ni las suites E2E completas (reservadas a PODA 2 y PODA 3).

## Decisions

### 1. Censo de consumidores desde la UI (UI-Driven Tracing)
- **Decisión:** El perímetro funcional se determina inspeccionando los servicios de Angular (`frontend/src/app/core/services/` y componentes de features). Todo endpoint de backend que no tenga llamada desde el cliente ni forme parte de la coordinación OpenSpec/health autorizada se clasifica como candidato a retiro.
- **Alternativas consideradas:** Retirar por intuición o antigüedad de archivos. Se descartó porque introduce riesgo de romper flujos sutiles. La trazabilidad formal garantiza evidencia objetiva.

### 2. Eliminación atómica de código y pruebas asociadas dentro del mismo Change
- **Decisión:** Cada ruta, controlador o servicio eliminado se desincorpora junto con sus archivos o casos de prueba en `tests/` dentro del mismo Change.
- **Alternativas consideradas:** Dejar los tests marcados como skip o eliminarlos en un PR posterior. Se descartó para evitar deuda técnica y divergencia entre código y tests.

### 3. Migraciones Alembic conservadoras y sincronización de metadatos
- **Decisión:** Toda tabla o columna a retirar se gestiona mediante una nueva revisión de Alembic con funciones `upgrade()` (eliminación) y `downgrade()` (recreación). Los modelos en `src/minime/models/` y los metadatos canónicos de SQLAlchemy se actualizan simultáneamente para mantener intactos los preflights de invariantes de esquema (`SCHEMA_INVARIANT_VIOLATION`).
- **Alternativas consideradas:** Truncar tablas o dejarlas abandonadas en PostgreSQL sin migración. Se descartó por violar el principio de persistencia limpia y determinismo de esquema.

### 4. Validación de no-regresión contra línea base del operador
- **Decisión:** La suite de pruebas conservada se ejecuta sobre el candidato en una base de datos desechable y su resultado se compara con el reporte previo del operador sobre el SHA base, asegurando exit code 0 y cero fallos en flujos activos.

## Risks / Trade-offs

- **[Riesgo] Retirar accidentalmente una ruta o dato utilizado por una acción poco frecuente de la UI**
  → *Mitigación:* Censo estático cruzado mediante grep sobre todo el código fuente de `frontend/` y registro de evidencia de cero consumidores antes de borrar.
- **[Riesgo] Inconsistencia en la verificación física de esquema en preflight (`check_schema_invariants`)**
  → *Mitigación:* Ajustar tanto el modelo SQLAlchemy canónico como la revisión Alembic al unísono, probando la verificación de preflight en tests de integración.
- **[Riesgo] Pérdida de información histórica en tablas retiradas**
  → *Mitigación:* Definir estrategia de respaldo lógico previo a la aplicación de la migración si existen datos que deban retenerse fuera de runtime.

## Migration Plan

1. **Auditoría:** Realizar censo de endpoints y tablas; publicar inventario de trazabilidad y candidatos a retiro.
2. **Poda de Backend:** Eliminar rutas, servicios y modelos huérfanos.
3. **Migración DB:** Crear revisión Alembic de desincorporación con upgrade y downgrade comprobados.
4. **Depuración de Tests:** Retirar pruebas obsoletas de componentes eliminados.
5. **Verificación:** Ejecutar la suite completa retenida en base aislada y contrastar con la línea base del operador.
6. **Rollback:** En caso de regresión o fallo, ejecutar `alembic downgrade -1` y revertir el commit del candidato.
