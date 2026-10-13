---
name: minime-engineering-discipline
description: "Comprobar coherencia de producto, rigor de ingeniería y anti-drift al proponer, aplicar y verificar cada Change."
---
# mini me — Engineering Discipline (v1)

**Extensión del workflow OpenSpec nativo del agente; nunca lo sustituye.** Lee `docs/BUSINESS_INTENT.md`, `docs/CANONICAL_DECISIONS.md`, `docs/PRODUCT.md`, `docs/ENGINEERING_DISCIPLINE.md`, `docs/CHANGE_DELIVERY_CONTRACT.md`, `AGENTS.md`, la ficha MM-Rxx y el único Change OpenSpec activo.

## En propose/design
1. Define antes/después verificable, actor y limitaciones. Cada spec debe tener SHALL/SHALL NOT, Given/When/Then, E2E de etapa, E2E vertical, E2E del comportamiento desplegado, regresión y excepción/denegación.
2. Haz el censo de servicios y callers, writers, Git/GitHub/DB, hooks/skills/comandos/harness existentes; registra reuse/modify/retire y opciones rechazadas.
3. Resuelve en design responsabilidades, cohesión, duplicación, capas, compatibilidad de API, identidad repo/WT, idempotencia/locks, manejo explícito de errores, seguridad, secretos, observabilidad, migración y rollback.
4. Genera Removal Ledger antes de apply. Si no se reemplaza nada: NONE y justificación.
5. Busca contradicciones con intención de producto y OpenSpec; detén cualquier plan que emule OpenSpec o recorte el valor acordado. Usa workflow OpenSpec update para resolver diferencias.

## En apply
- Usa exclusivamente el workflow OpenSpec apply instalado en el agente.
- Sigue el design aprobado; cambios de contrato → OpenSpec update, no improvisación.
- Código simple y mantenible, responsabilidades acotadas, reutilización y pruebas proporcionales al riesgo; no frameworks especulativos ni hacks de test.
- Implementa y verifica sustituto, migra consumidores, retira código obsoleto, **repite los tests/E2E después del retiro**.
- Preserva historias, Run/Job/attempts/worktrees, specs archivadas y migraciones ya aplicadas.

## En verify/review
- Contrasta producto → spec → design → código → pruebas → evidencia real → feature desplegada. Revisa seguridad, errores, concurrencia, mantenibilidad, UX y regresión.
- Asegura que Removal Ledger y ausencia de rutas duplicadas tienen evidencia, no solo grep.
- Reporta PASS/FAIL/BLOCKED con IDs, archivos, SHA y fallos; hooks/LLMs no se autoconceden aprobaciones.
- Si falta un E2E de agente real, el Change no está E2E_PASS. Si falta verificación funcional postdeploy, no está DONE.

**Autoridad:** esta skill orienta al agente, no concede permisos, no reemplaza guards ejecutables, no consume presupuestos ni autoriza merge.
