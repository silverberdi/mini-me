# Design

## Context

La propuesta describe la brecha funcional. El inventario actual muestra que `budget_ledger` ya existe y que `OperationsDashboardService.get_cost_projection` lee sus entradas, mientras la coordinación real pasa por `NativeOrchestrationCoordinator` y adaptadores de Codex, DeepSeek y OpenRouter. El diseño debe conectar el resultado de uso verificable con ese ledger sin convertir una consulta en una escritura ni crear una segunda autoridad financiera.

Restricciones: PostgreSQL/Alembic es el almacenamiento durable; las consultas del Dashboard son puras; el TTL reactivo de 300.000 ms permanece intacto; no se reintroducen topes artificiales; costos desconocidos no se convierten en cero; y toda integración afirmada requiere E2E observable.

## Goals / Non-Goals

**Goals:**

- Definir un único límite de liquidación reutilizable para invocaciones y etapas que entreguen uso y costo verificables.
- Preservar precisión monetaria, identidad de proveedor/modelo, timestamp, proyecto y una clave de idempotencia basada en la identidad de uso.
- Hacer atómica la persistencia con el resultado de ejecución y explícito el estado no liquidado ante fallo o evidencia insuficiente.
- Alimentar la proyección existente del Dashboard exclusivamente desde `budget_ledger` y demostrar el flujo completo en PostgreSQL y navegador.
- Retirar escritores, cálculos por tokens y fallbacks sintéticos duplicados que el censo confirme dentro del alcance, preservando datos históricos y migraciones aplicadas.

**Non-Goals:**

- Cambiar la arquitectura reactiva, `RefreshService.DASHBOARD_CACHE_TTL_MS`, la forma general de la PWA o la API de proveedores.
- Inventar precios para Codex, DeepSeek u OpenRouter cuando el contrato del proveedor no los exponga de forma verificable.
- Restaurar límites diarios/mensuales artificiales, migrar datos productivos manualmente, desplegar, reiniciar el scheduler o cerrar el Issue.

## Decisions

### 1. Reutilizar el ledger y sus repositorios como única autoridad

El flujo de ejecución llamará a un servicio/contrato pequeño de liquidación que reciba un resultado de uso normalizado y persista en el repositorio existente de `budget_ledger`. Se prefiere ampliar el modelo y repositorio actuales frente a crear tabla, proyección o caché paralela, porque el Dashboard ya tiene el lector y la autoridad contractual es PostgreSQL.

Alternativa descartada: calcular USD en `OperationsDashboardService` desde tokens; viola la prohibición de costos sintéticos y mezcla comando con consulta.

### 2. Idempotencia por identidad de uso observada

La clave estable de proveedor/invocación/etapa se conservará con una restricción única o el mecanismo equivalente ya soportado por el modelo. La operación será transaccional: una repetición devuelve la liquidación existente y un fallo de commit no se presenta como costo disponible.

Alternativa descartada: deduplicar solo en memoria o en el coordinador; se pierde ante reinicios y no protege contra concurrencia.

### 3. Normalizar resultados sin ocultar evidencia faltante

Cada adaptador conservará sus campos observados y entregará al límite común solo cuando proveedor, monto y timestamp sean verificables. Tokens sin precio, respuestas ambiguas y proveedor desconocido se registrarán como no resueltos mediante la ruta de resultado existente, sin insertar un `0` ni atribuir otro proveedor. El modelo concreto se mantiene nulo cuando no está disponible.

Alternativa descartada: usar un catálogo de precios local para estimar; no representa un costo observado y contradice el Issue.

### 4. Mantener la proyección actual y verificar el borde reactivo

`get_cost_projection` seguirá siendo una consulta pura y conservará sus estados `no_data`/`available`, agregaciones y filtrado de proveedores. Solo se ajustará si el censo demuestra que no acepta los nuevos registros. La prueba de navegador esperará la ruta de actualización ya declarada y comprobará la serie visible, sin cambiar el TTL ni añadir polling propio.

## Risks / Trade-offs

- **[Uso verificable pero precio ausente]** El Dashboard seguirá vacío para esa invocación → conservar estado UNKNOWN/UNSETTLED y evidencia para reconciliación, nunca estimar.
- **[Reintento concurrente duplica gasto]** → restricción/operación idempotente en PostgreSQL y prueba con dos intentos del mismo identificador.
- **[Diferencias entre contratos de proveedores]** → adaptadores entregan un DTO mínimo común; campos opcionales no se rellenan por inferencia.
- **[Writer legado continúa activo]** Dos fuentes podrían duplicar importes → Removal Ledger obligatorio: localizar writers y consumidores, probar la ruta nueva y retirar solo rutas alcanzables sustituidas; conservar historial y migraciones.
- **[E2E dependiente de credenciales externas]** No se puede fingir una invocación real → usar el harness/proveedor real configurado y detenerse fail-closed si la evidencia de uso/costo no es observable; los dobles quedan limitados a unit/contract tests.

## Migration Plan

1. Aplicar únicamente una migración Alembic si el censo confirma que falta la clave de idempotencia, precisión o metadato requerido; hacerla aditiva, reversible y compatible con las seis filas históricas existentes.
2. Implementar el límite común y conectar writers de ejecución; mantener datos históricos y sin backfill inventado.
3. Ejecutar pruebas enfocadas de persistencia, coordinador y proyección; después retirar cálculos/writers sustituidos y repetir la suite.
4. Ejecutar E2E real con PostgreSQL y navegador, capturando invocación, entrada del ledger, respuesta API y serie renderizada con el SHA del candidato.
5. Rollback: detener la nueva invocación de liquidación mediante la ruta de cambio, revertir la migración solo si no contiene datos nuevos o usar una migración compensatoria; no borrar entradas históricas ni ocultar un costo ya observado.

## Removal Ledger

Apply inventory (2026-11-23): the existing reservation settlement writers in
`BudgetService` remain valid for reserved spend, and direct review usage remains
an explicitly verified legacy path. No alternate ledger table or Dashboard
writer was found. The new boundary below is for provider invocations that
already expose an authoritative amount and usage identity without a reservation;
token counters alone remain non-financial evidence.

| Elemento | Acción prevista | Evidencia requerida |
| --- | --- | --- |
| Cálculo de costo desde tokens en writers o Dashboard | RETAIN only provider-reported `usage.cost`; REMOVE any token-only caller | búsqueda estática, pruebas negativas y E2E sin ledger |
| Writer de costos duplicado fuera del repositorio `budget_ledger` | NONE FOUND; new boundary writes only through existing repository | mapa de callers, diff y prueba de una sola entrada |
| Modelo, migración y filas históricas de `budget_ledger` | RETAIN | inventario de migraciones, conteo antes/después y consulta de lectura |
| `OperationsDashboardService.get_cost_projection` y contrato `no_data` | RETAIN, modificar solo si es necesario | pruebas API/UI y ausencia de mutaciones en GET |

## Open Questions

Ninguna cuestión abierta cambia el contrato: el censo de Apply determinará si el esquema existente ya dispone de una clave de idempotencia y qué proveedores exponen un importe verificable; si un proveedor no lo expone, el comportamiento especificado es permanecer no liquidado.
