## Why

F2 y F3 ya proporcionan catálogo de agentes, perfiles, aislamiento, GitHub, OpenSpec nativo y el recorrido de entrega, pero las capacidades reutilizables que hacen legible y repetible ese trabajo todavía no tienen un contrato único de F4. Sin una base mínima, cada proyecto Greenfield puede recibir instrucciones duplicadas, comentarios poco útiles o herramientas instaladas de forma inconsistente.

F4 consolida únicamente las capacidades que faltan, reutiliza las integraciones ya operativas y deja listo a mini me para ejecutar F5 sobre sí mismo sin crear otro orquestador ni alterar OpenSpec.

## What Changes

- Normalizar un Request remoto de prueba a Gherkin conservando íntegramente su cuerpo original en un comentario del mismo Issue, junto con adjuntos, comentarios y todos los criterios de aceptación identificados; publicar el resultado de forma idempotente y segura.
- Preparar comentarios de hitos, bloqueos, preguntas y cierre en español claro y breve, reutilizando el adaptador GitHub y el cierre gobernado por F3.
- Preparar PR de implementación y PR documental con la integración mínima de F3, sin decidir merges ni duplicar `minime-pr-preparer`.
- Definir un catálogo pequeño de capacidades reutilizables y su vinculación por perfil, incluyendo skills personalizadas, hooks, commands y harnesses solo cuando sean compatibles y necesarios.
- Integrar esa instalación y su preflight exclusivamente en el bootstrap Greenfield de F2; hacerla idempotente, no sobrescribir recursos ajenos y dejar Brownfield fuera del Change.
- Mantener los workflows oficiales OpenSpec, el confinamiento, los permisos, la continuidad, las cuotas y las decisiones humanas bajo sus propietarios actuales.
- Adaptar explícitamente las skills existentes `minime-engineering-discipline`, `minime-real-e2e-proof` y `minime-safe-retirement` en sus instalaciones Codex y Antigravity para alinearlas con F4.
- Establecer disciplina de código, pruebas unitarias/integración/E2E y retiro seguro de rutas realmente sustituidas, sin crear validadores semánticos, gates o frameworks de plugins paralelos.

## Capabilities

### New Capabilities

- `request-normalization-and-communication`: normalización Gherkin del Request y comentarios/cierre concretos en español mediante GitHub.
- `greenfield-agent-capability-bootstrap`: catálogo mínimo, selección por perfil, instalación idempotente y preflight de skills, hooks, commands y harnesses en Greenfield.
- `delivery-quality-and-safe-retirement`: orientación de calidad, pruebas E2E automatizadas y retiro seguro de consumidores y código sustituido dentro del Change.

### Modified Capabilities

None. F4 introduces the three focused capability contracts above; existing F2/F3
implementations are reused or adapted without rewriting their legacy spec
requirements. In particular, the historical local-worker and PR specs are not
silently expanded by this Change.

## Impact

- Afecta al bootstrap Greenfield, al catálogo de capacidades por perfil, al contexto que reciben los agentes y a los adaptadores existentes de GitHub y OpenSpec.
- Reutiliza `ProjectCatalogService`, los perfiles F2, `GreenfieldBootstrapCoordinator`, `OpenSpecAdapter`, la resolución de workflows, los runners/confinamiento, `GitHubAdapter`, el worktree guard y la skill mínima de PR de F3.
- Puede añadir solo contratos/manifestos y adaptaciones pequeñas en los propietarios existentes; no añade una API, un scheduler, una cola, un motor de plugins, un sustituto de OpenSpec ni una ruta de instalación Brownfield.
- S01 se prueba con un Issue de prueba controlado. El Issue #172 ya normalizado permanece como fuente de autoridad y no se reescribe durante F4; solo recibirá los comentarios y cierre legítimos que correspondan a su ciclo F3. Esta propuesta no ejecuta agentes, workflows de aplicación, migraciones, despliegues ni consumo de cuota.
