---
name: minime-real-e2e-proof
description: "Diseñar y verificar pruebas E2E auténticas de etapas, resultado del Change y despliegue."
---
# mini me — Real E2E Evidence (v1)

Extensión de OpenSpec propose/design/apply/verify. Consulta `AGENTS.md`, `openspec/config.yaml`, `context/INDEX.md` y los documentos que existan en el proyecto destinatario. Las referencias históricas o rutas `docs/` ausentes no son requisitos.

## Evidencia proporcional
- TECHNICAL_PASS: unit/integration/static para el contrato aislado.
- E2E_PASS: conducta externa real; **agente real usando su workflow OpenSpec instalado**, Git y GitHub reales cuando se afirma generar software/PR.
- El despliegue y la verificación postdeploy pertenecen al CI/CD del proyecto y solo se exigen cuando el Change los incluye explícitamente.
- Ejecuta las pruebas de base de datos en el stage más temprano que tenga el perfil de prueba aislado del proyecto (`test_database` y referencia host `_TEST_DATABASE_URL`). No solicites una respuesta humana para ejecutar una prueba automatizable. Solo difiere una prueba cuando el entorno requerido no está disponible en Apply/Verify y el proyecto la ejecuta en un check de PR explícitamente identificado, contra una base de pruebas aislada; conserva ese check y el SHA exacto como pendiente hasta el resultado concluyente de GitHub. Una configuración ausente o insegura y una cobertura CI ausente son fallos, no diferimientos.

## Evidencia mínima por escenario
`scenario_id`, input/operator action, inicio/fin, run/job/attempt, environment, project/repo, base/head SHA, workflow y versión OpenSpec, agente/modelo/rol, capabilities y versiones, artefactos/diff, checks/exit, reviewer independiente, URL PR, evidencia de side effects, digest deploy, verificación de feature, resultado, política/cuota y logs redactados.

## Diseño Given/When/Then
1. Happy path real y transición por etapa nueva; acción observable por API/UI/GitHub.
2. Rechazos relevantes: auth/quota, tool ausente, repo equivocado, filesystem escape, retries duplicados, sin reviewer independiente, falta de presupuesto, side effect UNKNOWN.
3. Recuperación: kill/restart en checkpoint y entre side effect/ack. Preservar el mismo Run/Job/worktree.
4. UI: navegador real desktop/tablet/mobile y escenarios humanos cuando aplica.
5. Regresión de las capacidades críticas pertinentes después de cualquier retiro dentro del Change.
6. Ejecutar el nivel apropiado para el proyecto; HTTP 200, una colección vacía o `pytest PASSED` sin pruebas no acreditan funcionalidad.

**No fingir:** fake runners sirven solo para tests acotados. Si la inferencia real no está autorizada: NOT_VERIFIED / WAITING_CAPACITY, nunca PASS. No iniciar consumo por ejecutar esta skill.

**Portabilidad:** la skill no exige copiar documentación privada o específica de mini me al proyecto Greenfield. Si una fuente recomendada no existe, registra `CONTEXT_NOT_AVAILABLE` y usa el contexto real disponible sin bloquear por una ruta histórica.
