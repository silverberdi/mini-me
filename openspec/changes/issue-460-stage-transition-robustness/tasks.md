## 1. Propuesta y validación

- [x] 1.1 Persistir en una sola transacción la aprobación independiente y los hashes de tareas/escenarios de la propuesta revisada; revalidar estrictamente y bloquear ante cambios de factibilidad no revalidados.
- [x] 1.2 Añadir al prompt nativo de Propose el recordatorio de escenarios por Requirement y comprobar que OpenSpec CLI sigue rechazando una delta spec sin escenario.

## 2. Candidato inmutable antes de Verify

- [x] 2.1 Crear y registrar el commit del candidato después de pruebas exitosas y antes de Verify; impedir Verify ante pruebas, commit, SHA o estado del árbol no verificables, sin incluir archivos ajenos al candidato.
- [x] 2.2 Cubrir con pruebas la secuencia Apply/corrección → pruebas → commit → Verify, confirmando que Verify recibe el SHA exacto y que una corrección posterior exige un SHA nuevo.

## 3. Despacho único de DOC_CLOSING

- [x] 3.1 Limitar la API a registrar idempotentemente la respuesta y dejar elegible el mismo Run; hacer que el Scheduler despache DOC_CLOSING bajo el claim durable existente.
- [x] 3.2 Tras `ACCEPTED`, mostrar inmediatamente en la PWA que la respuesta fue recibida y qué etapa está pendiente; mostrar inicio efectivo solo cuando lo confirme el Run actualizado y conservar el gate si la API falla.
- [x] 3.3 Probar en PostgreSQL el endpoint real de respuesta, el Scheduler separado y el reenvío idempotente; competir con dos workers a través del claim nativo de DOC_CLOSING y comprobar que solo uno registra `STAGE_INVOCATION_STARTED` para la misma acción.

## 4. Gates accionables

- [x] 4.1 Aplicar al payload existente de todos los tipos de Human Gate la descripción del bloqueo y evidencia afectada, el diff observado cuando aplique y explicaciones de acción/consecuencia para cada opción; probar gates de cada ruta existente y preservar valores nativos, redacción, autorización y compatibilidad.
- [x] 4.2 Hacer `diff`, `affected_items` y `option_explanations` opcionales de extremo a extremo y mostrarlos en la vista existente del gate sin cambiar el valor de respuesta; mantener funcionales los payloads históricos sin esos campos.

## 5. Verificación integrada

- [ ] 5.1 Ejecutar las pruebas pertinentes y un E2E integrado usando el endpoint API y el proceso Scheduler separados contra PostgreSQL; conservar evidencia observable de respuesta aceptada, claim, invocación y resultado, SHA del candidato y ausencia de despachos duplicados.
- [ ] 5.2 Ejecutar `openspec validate issue-460-stage-transition-robustness --strict --no-interactive` y comprobar los cinco criterios del Issue contra el mismo candidato inmutable.
