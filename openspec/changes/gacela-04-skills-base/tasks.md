## 1. Censo y contratos de F4

- [ ] 1.1 Confirmar en el código, tests y configuración los consumidores de ProjectCatalogService, perfiles F2, GreenfieldBootstrapCoordinator, OpenSpecAdapter, GitHubAdapter, guards, preflight y `minime-pr-preparer` de F3.
- [ ] 1.2 Inventariar las skills oficiales OpenSpec y las skills mini me instaladas, clasificando cada capacidad como REUSE, ADAPT o CREATE con procedencia y propietario.
- [ ] 1.3 Censar hooks, commands, harnesses, manifiestos y rutas históricas para identificar duplicados y conservar únicamente recursos compatibles con el contrato rector.
- [ ] 1.4 Definir el contrato de manifest/catálogo mínimo por perfil, incluyendo compatibilidad, procedencia, disponibilidad observable y ausencia de secretos.

## 2. Normalización del Request y comunicación

- [ ] 2.1 Implementar el flujo nativo de normalización Gherkin para el Issue remoto, conservando cuerpo original, comentarios, adjuntos y criterios con identificadores estables.
- [ ] 2.2 Reutilizar el adaptador GitHub para leer versión remota, detectar ediciones concurrentes y publicar la normalización sin sobrescrituras ni comentarios duplicados.
- [ ] 2.3 Implementar el formato breve en español para bloqueos, preguntas, hitos, resultados y cierre, con enlaces verificables y sin secretos ni logs extensos.
- [ ] 2.4 Integrar la deduplicación idempotente de comentarios y cierre con el coordinador F3, sin reimplementar estados, autorizaciones o merge.
- [ ] 2.5 Preparar los contenidos de PR de implementación y documental usando evidencia real y la skill mínima de PR de F3, sin directivas de cierre automático ni decisiones de merge.
- [ ] 2.6 Añadir pruebas de normalización ya-Gherkin, preservación de criterios, ambigüedad material, concurrencia, comentario idempotente y preparación de ambos PR.

## 3. Catálogo e instalación Greenfield

- [ ] 3.1 Implementar o adaptar el manifest de capacidades para seleccionar por perfil únicamente skills, hooks, commands, harnesses y OpenSpec compatibles observados en el catálogo real.
- [ ] 3.2 Integrar la instalación al bootstrap Greenfield existente, reutilizando la identidad de proyecto, worktree, confinamiento, OpenSpec oficial y checkpoint.
- [ ] 3.3 Hacer la instalación idempotente: reutilizar recursos compatibles, conservar archivos no autorizados para sustituir y preservar candidato, fuentes y evidencia ante conflictos.
- [ ] 3.4 Impedir toda instalación o modificación automática del paquete F4 en proyectos Brownfield y probar la frontera explícitamente.
- [ ] 3.5 Añadir el preflight ligero de disponibilidad por perfil, autenticación, capacidad, OpenSpec y seguridad sin crear un nuevo gate ni reinstalar en cada etapa.
- [ ] 3.6 Añadir pruebas de catálogo vacío, capacidad ausente, integración Verify ausente, conflicto de archivo, reanudación y no sobrescritura.

## 4. Harnesses de asistencia y disciplina

- [ ] 4.1 Adaptar el contexto entregado al agente para referenciar Request, adjuntos, comentarios, arquitectura, decisiones y código vigentes sin copias divergentes.
- [ ] 4.2 Reutilizar las skills de disciplina de ingeniería, E2E y retiro seguro donde ya existan; crear solo enlaces/contratos faltantes y documentar su procedencia.
- [ ] 4.3 Verificar que hooks y harnesses facilitan investigación, pruebas y revisión, pero no se convierten en gates, motores semánticos ni sustitutos de OpenSpec Verify.
- [ ] 4.4 Verificar que el revisor independiente recibe candidato, diff, contexto y pruebas en solo lectura y que no puede certificar su propia autoría.
- [ ] 4.5 Añadir pruebas contractuales de aislamiento, permisos, no exposición de secretos y preservación de decisiones humanas.

## 5. Calidad, E2E y retiro seguro

- [ ] 5.1 Definir la matriz de pruebas proporcional por tipo de proyecto, distinguiendo unitarias, integración, negativas, regresión y E2E real de mocks.
- [ ] 5.2 Implementar pruebas automatizadas del valor funcional de un Request vertical usando las interfaces reales apropiadas al fixture, sin exigir stack o despliegue ajeno.
- [ ] 5.3 Ejecutar un recorrido determinista Greenfield con agente simulado para instalación, normalización, comentarios, PR y validaciones técnicas, sin presentarlo como E2E de agente real.
- [ ] 5.4 Ejecutar el E2E autorizado de Greenfield con agente real cuando F3, credenciales, cuota, repositorio desechable y permisos estén verificables; conservar hashes, consumo y evidencias.
- [ ] 5.5 Censar consumidores estáticos, dinámicos y de configuración de cada ruta sustituida antes de retirar código, tests, dependencias o configuración.
- [ ] 5.6 Retirar solo las rutas huérfanas demostradas dentro de F4 y conservar consumidores legítimos, datos históricos y compatibilidad necesaria.
- [ ] 5.7 Ejecutar regresión después del retiro y registrar brevemente lo conservado y la razón, sin crear un Removal Ledger paralelo innecesario.

## 6. Aceptación y publicación de F4

- [ ] 6.1 Ejecutar pruebas focalizadas, integración, regresión, Ruff, validación OpenSpec estricta y comprobación de diff, corrigiendo únicamente defectos atribuibles a F4.
- [ ] 6.2 Verificar el recorrido Greenfield completo: Request Gherkin, instalación, disponibilidad Codex/Antigravity, comentarios, PR de implementación, merge conforme a F3, Sync/Archive nativos y PR documental.
- [ ] 6.3 Confirmar que no se modificó Brownfield, main, producción, PostgreSQL productivo, scheduler ni workflows oficiales OpenSpec.
- [ ] 6.4 Publicar el PR de implementación de F4 con evidencias y mantener las autorizaciones de merge bajo las reglas de F3.
- [ ] 6.5 Tras el merge autorizado, ejecutar Sync/Archive nativos y publicar el PR documental de F4 sin inventar resultados ni cerrar el Issue antes del segundo merge confirmado.
- [ ] 6.6 Verificar los criterios S01-S07, GF, HA, H y DONE del Change, actualizar el mismo Issue #172 de forma idempotente y dejar evidencia lista para que mini me pueda ejecutar F5.
