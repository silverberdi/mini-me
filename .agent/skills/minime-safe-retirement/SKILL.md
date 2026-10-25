---
name: minime-safe-retirement
description: "Retirar código muerto y rutas suplantadas dentro del mismo Change, sin perder historia ni regresiones."
---
# mini me — Safe Code Retirement (v1)

**Skill de apoyo para el OpenSpec apply/verify del mismo Change que sustituye una función.** Autoridad contextual: `AGENTS.md`, `openspec/config.yaml`, `context/INDEX.md` y las decisiones existentes del Change. Trabaja solo en el worktree asignado; ninguna ruta `docs/` histórica es obligatoria.

## Retiro proporcional
Cuando F4 sustituya una ruta, registra sus consumidores, la acción y la prueba pertinente de retiro. Si no sustituye ninguna ruta, indica brevemente `NONE`; no existe un Removal Ledger universal.

## Procedimiento
1. Enumerar llamadas estáticas **y** rutas dinámicas/configuraciones disponibles en el proyecto destinatario. Un símbolo sin referencias textuales puede seguir en uso.
2. Ejecutar las pruebas pertinentes del reemplazo con OpenSpec y agentes reales cuando la capacidad esté autorizada y disponible antes de eliminar lo antiguo.
3. Migrar consumidores, contratos y tests, sin borrar protección de regresión; versionar APIs o migraciones si corresponden.
4. Retirar writers viejos, flags de transición sin consumidores, adaptadores redundantes, scripts y dependencias huérfanos.
5. Repetir unit/integration, seguridad, E2E de etapa y regresión pertinentes **después** de la eliminación. El postdeploy solo aplica si forma parte del alcance.
6. Cuando histórico/seguridad impidan retiro: RETAIN-WITH-REASON + ruta deshabilitada, riesgo, dueño, fecha/condición de sunset y aprobación humana. No declarar desmonte terminado si sigue alcanzable.

Conserva servicios, datos y referencias históricas que aún tengan consumidores legítimos. No uses referencias R01–R10 para justificar retiros sin evidencia actual. No uses un prompt libre para programar.

**Portabilidad:** no copies documentación interna del repositorio de origen ni exijas fichas MM-Rxx, R01–R10 o Removal Ledgers universales en Greenfield. Si el contexto recomendado no existe, registra la ausencia y continúa con evidencia disponible.
