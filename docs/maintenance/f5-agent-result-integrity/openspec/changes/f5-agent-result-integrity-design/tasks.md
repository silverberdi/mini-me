## 1. Gobernanza, baseline y contrato antes de implementar

- [ ] 1.1 Confirmar explícitamente con el operador la ubicación canónica de esta especificación sin infringir el único Change F5 `gacela-05-ui-self-hosted`; **este borrador no constituye autorización de código**.
- [ ] 1.2 Congelar el inventario del código y de los consumidores realmente alcanzables desde Run F5 (codificador de CLI, normalización, Explore, Propose, clasificación, proposal review, Apply, Verify, code review, PR1/PR2, Sync/Archive, cierre). Documentar contratos y responsables sin aceptar ausencia de cobertura.
- [ ] 1.3 Conciliar `docs/CONTRATO_RECTOR.md` v1.3, `openspec/config.yaml`, specs F2/F3/F4 y protocolos `READY TO PROPOSE` / `READY_TO_PROPOSE`; aprobar una convención compatible por proveedor.
- [ ] 1.4 Inspeccionar en modo de solo lectura las versiones y capacidades **reales** de Codex y Antigravity sobre Ubuntu para el transporte de última respuesta, NDJSON/texto, manejo de errores y cierre de turno; registrar fixtures saneados, nunca credenciales.
- [ ] 1.5 Verificar el Run F5 y sus intentos previos de solo lectura; documentar qué veredictos finales son recuperables con evidencia fuente y cuáles permanecen ambiguos, sin editar `stop_details` ni reejecutar agentes.
- [ ] 1.6 Obtener aprobación del diseño y de los límites de seguridad, datos y reanudación antes de implementar.

## 2. Evidencia de transporte consistente (implementación futura condicionada)

- [ ] 2.1 Adaptar el `CliAgentRunner` existente para distinguir íntegramente respuesta final de diagnósticos truncables y resultado de proceso, preservando compatibilidad y roles/perfiles.
- [ ] 2.2 Implementar o reutilizar la extracción nativa de Codex que exige eventos completos, mensaje final y fin de turno confirmado; no permitir éxito desde eventos de herramientas o stdout/stderr incidental.
- [ ] 2.3 Implementar la extracción Antigravity **solo** con un formato final realmente verificado; rechazar de forma segura formatos desconocidos.
- [ ] 2.4 Conservar límites de bytes de respuesta, diagnóstico/memoria, saneamiento, confinamiento, ACL de archivos temporales, limpieza y protecciones de secreto; probar overlimit, timeout y credenciales.
- [ ] 2.5 Evitar nuevas tablas, colas, motores o estados paralelos; justificar y aprobar por separado cualquier persistencia nueva demostrablemente necesaria.

## 3. Integración de todos los consumidores del ciclo nativo

- [ ] 3.1 Normalización F4 y preparación de PR: validar respuesta final estructurada y postcondiciones GitHub, manteniendo idempotencia y fidelidad al original.
- [ ] 3.2 Explore: aceptar solo veredicto final inequívoco y forma canónica documentada; distinguir herramientas/citas, preguntas reales, salidas truncadas y errores.
- [ ] 3.3 Propose: exigir native workflow, archivos exactos de Change y `openspec validate ... --strict --type change` como gate; ningún texto sustituye artefactos.
- [ ] 3.4 Complejidad y revisión independiente de propuesta: usar resultado final íntegro estructurado y evidencia de propuesta, preservar independencia y hashes.
- [ ] 3.5 Apply y Verify: corroborar ejecución nativa, candidato, tareas, pruebas y veredicto final, sin que `exit_code=0` baste para cambiar de etapa.
- [ ] 3.6 Review de código: usar solo respuesta final del revisor independiente, estricta y ligada a SHA; no `full_output` como fuente de autorización.
- [ ] 3.7 Sync/Archive y PR2/cierre: exigir archivos/estado nativo y confirmación remota, sin duplicar workflows por reinicio.

## 4. Persistencia, recuperación y seguridad

- [ ] 4.1 Probar y adaptar checkpoints sobre el Run persistente actual con fuente, hash, workflow, perfil, contexto, turno y etapa verificables; un SHA bien formado no es prueba de origen.
- [ ] 4.2 Implementar la reconciliación de crash, doble petición de continuación, veredicto previo válido, intento ambiguo y aclaración nueva sin nueva cola ni duplicar inferencia.
- [ ] 4.3 Verificar que fallos técnicos no crean HUMAN_REQUIRED de negocio y que decisión humana durable tiene autorización exacta del gate.
- [ ] 4.4 Confirmar ausencia de bypass de cuotas, políticas de pago, provider fallback, scheduler y merge humano; medir uso solo con observaciones proveedor.

## 5. Matriz automatizada y E2E sin gasto imprevisto

- [ ] 5.1 Convertir todos los escenarios de las 3 specs y `evidence/acceptance-matrix.md` en tests con entradas reales saneadas o fixtures identificados: NDJSON largo, stdout/stderr grande, mensaje final grande, formato alternativo, JSON malformado, truncación verdadera, timeout y conflicto.
- [ ] 5.2 Ejecutar pruebas unitarias/integración de runner, normalización, Explore, revisión, Verify, PR y recuperación; comparar baseline contra candidato, clasificar solo fallos atribuibles al cambio.
- [ ] 5.3 E2E offline de orquestación del mismo Run bajo persistencia y worktree desechables: Explore→Propose→strict→complejidad→Apply→Verify→PR1→Sync/Archive→PR2; simular GitHub remota/roles donde aplique sin fingir que simula modelos reales.
- [ ] 5.4 E2E real con procesos Codex/AGY solo bajo autorización expresa y presupuesto/capacidad verificables; comprobar un único despacho y trabajo efectivo, sin scheduler productivo.
- [ ] 5.5 `ruff check`, `ruff format --check`, `git diff --check`, regresión amplia, cobertura de consumidores y salida en español; ningún error conocido sin clasificar.
- [ ] 5.6 `openspec validate <change-canonico> --strict --type change` **PASS real** en workspace autorizado; registrar SHA, versión OpenSpec y stdout/stderr del CLI. Revalidar tras cualquier ajuste.
- [ ] 5.7 Revisión arquitectónica independiente de cumplimiento de límites, exactitud de evidencias y cero cambios de alcance F6/F7/F8.

## 6. Entrega gobernada y reanudación posterior (no autorizadas por el borrador)

- [ ] 6.1 Publicar artefactos y evidencia en el repositorio y PR solo con autorización específica, sin merges implícitos.
- [ ] 6.2 Tras aprobación explícita de merge y despliegue, respaldar y actualizar API manteniendo scheduler inactive/disabled; no migraciones salvo nueva decisión fundamentada.
- [ ] 6.3 Reanudar únicamente Run `4eb3f3f7-41df-4483-9a97-ce59bbcc0db2` con autorización particular de agente/modelo/gate; no generar otro Issue/Run/Change ni inferir recuperación de intentos antiguos.
- [ ] 6.4 Acreditar F5 real solo mediante PR1, merge gobernado, Sync/Archive nativos, PR2, merge, cierre Issue #173 y pruebas auténticas de UI. Nunca considerar la aprobación de este documento como F5 terminada.
