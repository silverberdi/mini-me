---
name: minime-engineering-discipline
description: "Comprobar coherencia de producto, rigor de ingeniería y anti-drift al proponer, aplicar y verificar cada Change."
---
# mini me — Engineering Discipline (v1)

**Extensión del workflow OpenSpec nativo del agente; nunca lo sustituye.** Lee `docs/BUSINESS_INTENT.md`, `docs/CANONICAL_DECISIONS.md`, `docs/PRODUCT.md`, `docs/ENGINEERING_DISCIPLINE.md`, `docs/CHANGE_DELIVERY_CONTRACT.md`, `AGENTS.md`, la ficha MM-Rxx y el único Change OpenSpec activo.

## En propose/design
1. Define antes/después verificable, actor y limitaciones. Ajusta pruebas y evidencia al comportamiento entregado; no impongas stacks, despliegues ni gates universales ajenos al Change.
2. Haz el censo de servicios y callers, writers, Git/GitHub/DB, hooks/skills/comandos/harness existentes; registra reuse/modify/retire y opciones rechazadas.
3. Resuelve en design responsabilidades, cohesión, duplicación, capas, compatibilidad de API, identidad repo/WT, idempotencia/locks, manejo explícito de errores, seguridad, secretos, observabilidad, migración y rollback.
4. Identifica consumidores sustituidos y registra evidencia concisa de retiro solo cuando este Change reemplace algo. No existe un Removal Ledger universal.
5. Busca contradicciones con intención de producto y OpenSpec; detén cualquier plan que emule OpenSpec o recorte el valor acordado. Usa workflow OpenSpec update para resolver diferencias.

## En apply
- Usa exclusivamente el workflow OpenSpec apply instalado en el agente.
- Sigue el design aprobado; cambios de contrato → OpenSpec update, no improvisación.
- Código simple y mantenible, responsabilidades acotadas, reutilización y pruebas proporcionales al riesgo; no frameworks especulativos ni hacks de test.
- Implementa y verifica el sustituto, migra consumidores y retira solo código demostrado obsoleto; repite las pruebas pertinentes después del retiro.
- Preserva historias, Run/Job/attempts/worktrees, specs archivadas y migraciones ya aplicadas.

## En verify/review
- Contrasta producto → spec → design → código → pruebas → evidencia real → feature desplegada. Revisa seguridad, errores, concurrencia, mantenibilidad, UX y regresión.
- Asegura que la retirada y ausencia de rutas duplicadas, cuando aplique, tienen evidencia más allá de un grep.
- Reporta PASS/FAIL/BLOCKED con IDs, archivos, SHA y fallos; hooks/LLMs no se autoconceden aprobaciones.
- Si se afirma una integración de agente real y no existe evidencia, registra NOT_VERIFIED/WAITING_CAPACITY; el despliegue pertenece al CI/CD del proyecto.

**Autoridad:** esta skill orienta al agente, no concede permisos, no reemplaza guards ejecutables, no consume presupuestos ni autoriza merge.
