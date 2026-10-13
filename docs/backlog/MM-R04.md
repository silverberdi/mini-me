# MM-R04 — native-openspec-delivery-and-closure

**Estado:** PLANNED; **Dependencias:** MM-R03; **Entrega:** Cierre sin emular OpenSpec; **no autoriza** activar scheduler/consumir cuotas sin aprobación; merge humano obligatorio.

## Business intent y antes/después
**Antes:** La reconciliación posmerge de mini me implementa fusiones y movimientos de specs en Python; que termine una saga no acredita semántica OpenSpec ni despliegue verificado.

**Después del despliegue:** Un PR fusionado por humano termina en un estado DONE solo cuando la entrega está verificada en destino, los workflows nativos de sincronización/archivo se han ejecutado con autoridad Git, GitHub está reconciliado y no quedan side effects inciertos.

## Specs mínimas que el agente debe elaborar durante `propose`
Cada Sxx se convierte en requisitos SHALL/SHALL NOT con al menos un escenario observable y un caso de rechazo/recovery. Se pueden agrupar specs relacionadas siempre que permanezca trazabilidad Sxx→test→evidencia; no basta con copiar esta lista a tasks. Source of truth: `docs/CHANGE_DELIVERY_CONTRACT.md` y docs canónicos.

### R04-S01 — Merge real
SHALL comprobar GitHub PR merged y candidato entregado a la rama base, con tratamiento fail-closed de squash/merge, sin false positive por nombres de branch.

### R04-S02 — Workflow OpenSpec
SHALL delegar semántica de `sync`/`archive` a workflows OpenSpec soportados por el agente (CLI nativo cuando sea la ruta válida), con versión, diff de spec, corroboración y cumplimiento de completion. Retirar código propio solo al tener paridad demostrada.

### R04-S03 — Autoridad Git posmerge
SHALL resolver explícitamente dónde se escriben los artefactos luego del merge: los cambios de código/spec que requieran Git NO se pushean directamente a rama protegida sin revisión/merge humano. Preferir incorporación al PR original cuando política/orden lo permitan; de lo contrario rama/PR de cierre con autorización. SHALL NOT simular DONE ignorando git remoto.

### R04-S04 — Entrega autorizada
SHALL realizar despliegue según contrato del repositorio y política humana, verificar artefacto/digest, migraciones/rollback, URL de destino y comportamiento funcional postdeploy.

### R04-S05 — Saga y reconciliación
SHALL registrar phases y side effects con idempotency keys; status UNKNOWN se observa antes de reintentar. GitHub Issue y Project solo pasan a Done después de confirmar archivo y despliegue aplicable.

### R04-S06 — Cleanup seguro
SHALL preservar worktrees ajenos/dirty, detener cleanup si ref de archivo no existe o hay conflicto, y dejar evidencia del SHA final; no borrar worktree con trabajo activo.

### R04-S07 — Defensa ante drift
SHALL comprobar que main specs y cambio archivado preservan todos los requisitos/escenarios, incluidas modificaciones y eliminación de requisitos; la simple concatenación de texto NO equivale a sync correcto.

## E2E obligatorios de etapa y de valor
Cada E0x debe describirse en OpenSpec como Given/When/Then con setup, salida y evidence path. Fake providers/mocks pueden servir a integration, **no** a la demostración de capacidad real. Además ejecutar regresión de R01–R03 y verificar en entorno desplegado.

### R04-E01 — Merge hasta DONE
Dado PR de R03 fusionado manualmente, mini me detecta el merge, ejecuta native sync/archive con el agente, completa despliegue de fixture, comprueba feature en destino, actualiza Issue/Project y limpia solo recursos propios; evidencia de cada paso.

### R04-E02 — Deltas no triviales
Usar OpenSpec delta ADDED/MODIFIED/REMOVED/RENAMED donde soporte CLI instalado; verificar specs canon resultantes, historial archivado y diffs sin pérdida semántica.

### R04-E03 — Squash GitHub
Fusionar PR fixture por squash y verificar ancestry/candidate delivery correcto; no falsificar completitud de merge.

### R04-E04 — Git protegido
Si sync/archive requiere commit posmerge, branch/PR con human gate obligatorio; intento push directo protegido se deniega. Ningún cambio no revisado se introduce por cleanup.

### R04-E05 — Fallo a mitad de saga
Reinicio justo después de archive remoto o Issue close pero antes de DB ack: reconciliar sin duplicar, pérdida de spec ni cierre prematuro.

### R04-E06 — Deployment fail
Simular health exitoso pero feature rota o migración incompatible; NO DONE, registrar ruta de rollback/incident sin destruir evidencia.

### R04-E07 — Postdeploy real
Validación desde endpoint/dominio de destino del cambio entregado, no solo GET /health; registrar pruebas funcionales y origen del deploy.

## Trabajo que debe quedar dentro del mismo Change
- Reutilizar sagas de post_merge_service.py, reconciler y GitHub sync; reemplazar fusionador/archiver propio mediante adaptador de workflow real y proof of invocation.
- Precisar estrategia canonical de branch/PR posmerge y captura de diff; sin merges automatizados.
- Incluir migración compatible que no mueva specs históricos irreversiblemente hasta completar dry run y E2E.

## No-goals y guardrails
NO rediseñar scheduler ni añadir optimizaciones de UX generales. No usar `openspec archive -y` para saltarse validación o aceptar tareas incompletas; autorización debe provenir del gate humano/política.

## Prueba de aceptación verificable
URLs PR/merge + SHA, transcript sync/archive nativos, comparación requisitos antes/después, ref de archivo, deployment digest + escenario funcional postdeploy, Issue/Project y evidencias de saga/rollback.

## Migración, release y recuperación
En fixture GitHub de prueba con rama protegida, no en producción antes de autorizar. Capturar snapshot y backup de DB si se necesitan migraciones. PR de cierre humano donde aplique. El `design.md` resolverá estrategia de migración/rollback cuando exista impacto de DB/Git/estado, y demostrará reconciliación tras failpoint. `DONE` exige TECHNICAL_PASS + E2E_PASS + DEPLOYED_VERIFIED y gates humanos/closure aplicables; antes de eso es `PLANNED`, `IN_PROGRESS` o `BLOCKED`, nunca entrega ficticia.

## Flujo permitido
Invocar el workflow agent-led `propose native-openspec-delivery-and-closure` en el agente disponible/instalado. Contrastar proposal/design/specs/tasks con esta ficha antes de `apply`. Cada modificación de alcance va por `update`. Verificar con `verify`, checks reales y guards; cierre `sync/archive` según contrato. **mini me coordina stages; la IA mediante OpenSpec escribe y verifica.**
