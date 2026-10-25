# F4 — Matriz de aceptación del Issue #172

Fecha: 2026-10-25. La matriz cubre los 35 criterios definidos en `design.md`. `PASS` significa que la evidencia citada demuestra el criterio; `PARCIAL` indica contrato o evidencia local sin el efecto remoto final; `PENDIENTE` requiere una operación aún no ejecutada. La matriz no convierte mocks en E2E ni el PR Greenfield en PR1.

| Criterio | Estado | Evidencia |
|---|---|---|
| S01_AC01 Request completo en Gherkin antes de Explore | PASS | `f4-normalization-e2e-issue5-recovery-20261025.md`; GET remoto del Issue #5 confirma `# language: es`, una Característica, tres Escenarios y pasos Gherkin con C1-C3 antes de Explore. |
| S01_AC02 cuerpo original literal preservado | PASS | `f4-normalization-e2e-issue5-recovery-20261025.md`; comentario remoto `6400977375` conserva literalmente el Request original y el marcador del mismo Run. |
| S01_AC03 criterios trazables sin invención | PASS | `f4-e2e-real-bootstrap-20261025.md`; tests focalizados de normalización. |
| S01_AC04 ambigüedad material y fallos técnicos separados | PASS | `f4-local-validation.md`; contrato fail-closed y rutas técnicas. |
| S01_AC05 concurrencia e idempotencia | PASS | tests focalizados de concurrencia/comentario idempotente en `f4-local-validation.md`. |
| S02_AC01 comunicación semántica breve en español | PASS | `f4-normalization-e2e-issue5-recovery-20261025.md`; comentario remoto `6400977558` contiene el mensaje semántico breve en español y el marcador del mismo Run. |
| S02_AC02 comentarios idempotentes y sin secretos | PASS | tests de GitHub/normalización y validación de seguridad en `f4-local-validation.md`. |
| S03_AC01 PR de implementación basado en Request y evidencia | PASS | PR1 F4: https://github.com/silverberdi/mini-me/pull/182, head `612d6c56d95b0069702c3473760d0745a3a5723c`; contenido preparado y validado por `PrPreparerService`, sin directiva de cierre automático. |
| S03_AC02 PR documental gobernado por F3 | PENDIENTE | depende del merge humano del PR1 y Sync/Archive. |
| S05_AC01 disciplina contextual | PASS | skills portables en ambas instalaciones y `f4-local-validation.md`. |
| S05_AC02 asistencia no convertida en gate | PASS | contratos de hooks/harnesses y pruebas focalizadas. |
| S05_AC03 sin autoridad OpenSpec paralela | PASS | OpenSpec strict PASS y diseño vigente. |
| S06_AC01 evidencia proporcional de pruebas | PASS | `f4-local-validation.md`: 57 pruebas focalizadas, Ruff, strict y diff check. |
| S06_AC02 E2E real de la interfaz apropiada | PASS | `f4-e2e-real-bootstrap-20261025.md`: Codex real, validación del candidato y PR #4. |
| S06_AC03 E2E no simulado y límites económicos | PASS | invocación real registrada, cero reintentos/fallback; consumo observable y límites en la evidencia E2E. |
| S07_AC01 retiro basado en consumidores | PASS | censo y pruebas de retiro documentados por `f4-local-validation.md`. |
| S07_AC02 consumidores históricos legítimos conservados | PASS | misma evidencia y diff del candidato. |
| GF_AC01 catálogo por perfil | PASS | instalación observada en `f4-e2e-real-bootstrap-20261025.md`. |
| GF_AC02 instalación oficial OpenSpec | PASS | instalación y workflows oficiales observados en la evidencia E2E. |
| GF_AC03 instalación idempotente/no destructiva | PASS | pruebas de conflicto, reanudación y no sobrescritura. |
| GF_AC04 Brownfield protegido | PASS | tests contractuales y `f4-e2e-real-bootstrap-20261025.md`. |
| GF_AC05 readiness para F5 sin implementar F5 | PASS | validación aislada de perfiles, OpenSpec, Worktree, confinamiento y GitHub; no se ejecutó F5. |
| HA01_AC01 identidad y permisos verificables | PASS | preflight Ubuntu y publicación/merge de PR #4 mediante App. |
| HA02_AC01 continuidad y recuperación | PASS | reconciliación durable en `f4-greenfield-merge-reconciliation-20261025.md`. |
| HA03_AC01 seguridad, aislamiento y secretos | PASS | preflight y controles del candidato; no hubo modificaciones productivas. |
| HA04_AC01 gasto y capacidad controlados | PASS | autorización, perfil, consumo observable y cero fallback registrados en la evidencia E2E. |
| H01_AC01 decisión humana de merge respetada | PASS | PR #4 fue fusionado después de la aprobación publicada; PR1 F4 seguirá pendiente. |
| H02_AC01 fallos técnicos no escalados como decisiones | PASS | rutas de recuperación y fail-closed en tests focalizados. |
| H03_AC01 ausencia de despliegue/scheduler | PASS | evidencias E2E y reconciliación confirman no despliegue, no scheduler. |
| F3_AC01 normalización y contexto entregados al coordinador | PASS | integración F4/F3 y evidencia de contexto real. |
| F3_AC02 PRs conservan identidad y SHA | PASS | PR #4 y PR1 #182 tienen repositorio, base, branch y head SHA verificados; el PR1 sigue sin fusionar. |
| F3_AC03 merges y cierre bajo autoridad F3 | PENDIENTE | PR1 F4 ya tiene merge humano confirmado; todavía faltan Sync/Archive, PR2 y cierre remoto del Issue. |
| F3_AC04 recuperación sin consumo duplicado | PASS | intento único, recuperación post-inferencia y reconciliación durable. |
| DONE_AC01 aceptación remota completa | PENDIENTE | falta PR1, merge humano, Sync/Archive y PR2. |
| DONE_AC02 F5 preparado sin ejecutar F5 | PASS | Greenfield aislado validado; no se instaló Brownfield ni se ejecutó F5. |

## Estado

La publicación remota del Run existente demuestra los tres criterios antes parciales: S01_AC01, S01_AC02 y S02_AC01 pasan con evidencia del Issue #5. PR1 ya está fusionado y las specs F4 están sincronizadas. Las tareas 6.2, 6.5 y 6.6 tienen evidencia `PRE_MERGE_VERIFIED`, pero permanecen abiertas hasta completar Archive nativo, PR2 fusionado y cierre remoto del ciclo; no se marca ninguna postcondición por anticipado. El Issue #172 no fue reescrito. Ver `f4-closure-gates-20261025.md`.
