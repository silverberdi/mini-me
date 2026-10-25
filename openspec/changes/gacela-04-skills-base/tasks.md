## 1. Censo y contratos de F4

- [x] 1.1 Confirmar en el código, tests y configuración los consumidores de ProjectCatalogService, perfiles F2, GreenfieldBootstrapCoordinator, OpenSpecAdapter, GitHubAdapter, guards, preflight y `minime-pr-preparer` de F3.
- [x] 1.2 Inventariar las skills oficiales OpenSpec y las skills mini me instaladas, clasificando cada capacidad como REUSE, ADAPT o CREATE con procedencia y propietario.
- [x] 1.3 Censar hooks, commands, harnesses, manifiestos y rutas históricas para identificar duplicados y conservar únicamente recursos compatibles con el contrato rector.
- [x] 1.4 Definir el contrato de manifest/catálogo mínimo por perfil, incluyendo compatibilidad, procedencia, disponibilidad observable y ausencia de secretos.

## 2. Normalización del Request y comunicación

- [x] 2.1 Implementar el flujo nativo de normalización Gherkin como primer paso del mismo Run, después de admitir el Request y preparar su Worktree pero antes de Explore, transformando completamente el cuerpo de un Issue de prueba controlado y conservando el cuerpo original íntegro en un comentario del mismo Issue, junto con comentarios, adjuntos y criterios con identificadores estables; un Issue ya normalizado continúa sin reescritura.
- [x] 2.2 Reutilizar el adaptador GitHub para leer versión remota, aplicar concurrencia optimista, detectar ediciones concurrentes y publicar o reconciliar la normalización sin sobrescrituras ni comentarios duplicados, confirmando remotamente el cuerpo y el comentario original antes de Explore.
- [x] 2.3 Implementar el formato breve en español para bloqueos, preguntas, hitos, resultados y cierre, con enlaces verificables y sin secretos ni logs extensos.
- [x] 2.4 Integrar la deduplicación idempotente de comentarios y cierre con el coordinador F3, sin reimplementar estados, autorizaciones o merge.
- [x] 2.5 Adaptar `PrPreparerService` para que `minime-pr-preparer` redacte semánticamente los contenidos de PR de implementación y documental a partir del Request y la evidencia real; mantener en código la identidad, base/head SHA, validación, referencias no cerradoras, publicación y ausencia de directivas de cierre automático o decisiones de merge, conforme a las reglas F3.
- [x] 2.6 Añadir pruebas del Issue controlado para normalización ya-Gherkin antes de Explore, preservación completa del cuerpo original y criterios, ambigüedad material, concurrencia, comentario idempotente, confirmación remota y preparación de ambos PR; no modificar ni reescribir el Issue #172.

## 3. Catálogo e instalación Greenfield

- [x] 3.1 Implementar o adaptar el manifest de capacidades para seleccionar por perfil únicamente skills, hooks, commands, harnesses y OpenSpec compatibles observados en el catálogo real.
- [x] 3.2 Integrar la instalación al bootstrap Greenfield existente, reutilizando la identidad de proyecto, worktree, confinamiento, OpenSpec oficial y checkpoint, y dejar registrada la preparación aislada necesaria para que mini me pueda ejecutar F5 posteriormente sin implementar F5 ni instalar en Brownfield.
- [x] 3.3 Hacer la instalación idempotente: reutilizar recursos compatibles, conservar archivos no autorizados para sustituir y preservar candidato, fuentes y evidencia ante conflictos.
- [x] 3.4 Impedir toda instalación o modificación automática del paquete F4 en proyectos Brownfield y probar la frontera explícitamente.
- [x] 3.5 Añadir el preflight ligero de disponibilidad por perfil Codex/Antigravity, autenticación, capacidad, OpenSpec y seguridad sin crear un nuevo gate ni reinstalar en cada etapa.
- [x] 3.6 Añadir pruebas de catálogo vacío, capacidad ausente, integración Verify ausente, conflicto de archivo, reanudación y no sobrescritura.

## 4. Harnesses de asistencia y disciplina

- [x] 4.1 Adaptar el contexto entregado al agente para referenciar Request, adjuntos, comentarios, arquitectura, decisiones y código vigentes sin copias divergentes.
- [x] 4.2 Adaptar en paralelo `.agents/skills/` y `.agent/skills/` las skills `minime-engineering-discipline`, `minime-real-e2e-proof` y `minime-safe-retirement`, retirando requisitos heredados incompatibles sobre artefactos OpenSpec, postdeploy, Removal Ledger universal y R01–R10; conservarlas como orientación, no gates.
- [x] 4.3 Verificar que hooks y harnesses facilitan investigación, pruebas y revisión, pero no se convierten en gates, motores semánticos ni sustitutos de OpenSpec Verify; los fallos técnicos siguen recuperación y solo decisiones materiales/autorizaciones usan HUMAN REQUIRED.
- [x] 4.4 Verificar que el revisor independiente recibe candidato, diff, contexto y pruebas en solo lectura y que no puede certificar su propia autoría.
- [x] 4.5 Añadir pruebas contractuales de aislamiento, permisos, no exposición de secretos y preservación de decisiones humanas.

## 5. Calidad, E2E y retiro seguro

- [x] 5.1 Definir la matriz de pruebas proporcional por tipo de proyecto, distinguiendo unitarias, integración, negativas, regresión y E2E real de mocks.
- [x] 5.2 Implementar pruebas automatizadas del valor funcional de un Request vertical usando las interfaces reales apropiadas al fixture, sin exigir stack o despliegue ajeno.
- [x] 5.3 Ejecutar un recorrido determinista Greenfield con agente simulado para instalación, normalización, comentarios, PR y validaciones técnicas, sin presentarlo como E2E de agente real.
- [ ] 5.4 Ejecutar el E2E autorizado de Greenfield con agente real cuando F3, credenciales, cuota, repositorio desechable y permisos estén verificables; demostrar normalización real, capacidades Codex/Antigravity, GitHub y coordinación F3, conservar hashes, consumo y evidencias, y reutilizar evidencia F3 válida sin repetir su E2E.
- [x] 5.5 Censar consumidores estáticos, dinámicos y de configuración de cada ruta sustituida antes de retirar código, tests, dependencias o configuración.
- [x] 5.6 Retirar solo las rutas huérfanas demostradas dentro de F4 y conservar consumidores legítimos, datos históricos y compatibilidad necesaria.
- [x] 5.7 Ejecutar regresión después del retiro y registrar brevemente lo conservado y la razón, sin exigir un Removal Ledger universal o verificaciones postdeploy fuera del alcance.

## 6. Aceptación y publicación de F4

- [x] 6.1 Ejecutar pruebas focalizadas, integración, regresión, Ruff, validación OpenSpec estricta y comprobación de diff, corrigiendo únicamente defectos atribuibles a F4.
- [ ] 6.2 Verificar el recorrido Greenfield completo: normalización Gherkin antes de Explore, instalación, disponibilidad Codex/Antigravity, preservación del cuerpo original y comentarios, PR de implementación, merge conforme a F3, Sync/Archive nativos y PR documental, reutilizando evidencia F3 vigente por identidad exacta.
- [x] 6.3 Confirmar que no se modificó Brownfield, main, producción, PostgreSQL productivo, scheduler ni workflows oficiales OpenSpec.
- [ ] 6.4 Publicar el PR de implementación de F4 con evidencias y mantener las autorizaciones de merge bajo las reglas de F3.
- [ ] 6.5 Tras el merge autorizado, ejecutar Sync/Archive nativos y publicar el PR documental de F4 sin inventar resultados ni cerrar el Issue antes del segundo merge confirmado.
- [ ] 6.6 Verificar los 35 criterios S01-S07, GF, HA, H, F3 y DONE del Issue #172 mediante una matriz de evidencia contra el Issue de prueba controlado; conservar #172 como fuente ya normalizada sin reescribirlo, limitar sus cambios a comentarios/cierre legítimos de F3, reutilizar evidencia F3 válida y dejar evidencia de perfiles, workflows, coordinación y preparación aislada lista para que mini me pueda ejecutar F5 sin implementar F5.
