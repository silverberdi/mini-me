---
name: minime-real-e2e-proof
description: "Diseñar y verificar pruebas E2E auténticas de etapas, resultado del Change y despliegue."
---
# mini me — Real E2E Evidence (v1)

Extensión de OpenSpec propose/design/apply/verify. Consulta `docs/CHANGE_DELIVERY_CONTRACT.md` y `docs/ENGINEERING_DISCIPLINE.md`; no trates fichas MM-Rxx históricas como requisitos actuales.

## Evidencia proporcional
- TECHNICAL_PASS: unit/integration/static para el contrato aislado.
- E2E_PASS: conducta externa real; **agente real usando su workflow OpenSpec instalado**, Git y GitHub reales cuando se afirma generar software/PR.
- El despliegue y la verificación postdeploy pertenecen al CI/CD del proyecto y solo se exigen cuando el Change los incluye explícitamente.

## Evidencia mínima por escenario
`scenario_id`, input/operator action, inicio/fin, run/job/attempt, environment, project/repo, base/head SHA, workflow y versión OpenSpec, agente/modelo/rol, capabilities y versiones, artefactos/diff, checks/exit, reviewer independiente, URL PR, evidencia de side effects, digest deploy, verificación de feature, resultado, política/cuota y logs redactados.

## Diseño Given/When/Then
1. Happy path real y transición por etapa nueva; acción observable por API/UI/GitHub.
2. Rechazos relevantes: auth/quota, tool ausente, repo equivocado, filesystem escape, retries duplicados, sin reviewer independiente, falta de presupuesto, side effect UNKNOWN.
3. Recuperación: kill/restart en checkpoint y entre side effect/ack. Preservar el mismo Run/Job/worktree.
4. UI: navegador real desktop/tablet/mobile y escenarios humanos cuando aplica.
5. Regresión de todas las capacidades críticas previas después del Removal Gate.
6. Ejecutar el nivel apropiado para el proyecto; HTTP 200, una colección vacía o `pytest PASSED` sin pruebas no acreditan funcionalidad.

**No fingir:** fake runners sirven solo para tests acotados. Si la inferencia real no está autorizada: NOT_VERIFIED / WAITING_CAPACITY, nunca PASS. No iniciar consumo por ejecutar esta skill.
