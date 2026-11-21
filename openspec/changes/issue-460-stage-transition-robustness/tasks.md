## 1. Propuesta y validación

- [ ] 1.1 Persistir en una sola transacción la aprobación independiente y los hashes de tareas/escenarios de la propuesta revisada; revalidar estrictamente y bloquear ante cambios de factibilidad no revalidados.
- [ ] 1.2 Añadir al prompt nativo de Propose el recordatorio de escenarios por Requirement y comprobar que OpenSpec CLI sigue rechazando una delta spec sin escenario.

## 2. Candidato inmutable antes de Verify

- [ ] 2.1 Crear y registrar el commit del candidato después de pruebas exitosas y antes de Verify; impedir Verify ante pruebas, commit, SHA o estado del árbol no verificables, sin incluir archivos ajenos al candidato.
- [ ] 2.2 Cubrir con pruebas la secuencia Apply/corrección → pruebas → commit → Verify, confirmando que Verify recibe el SHA exacto y que una corrección posterior exige un SHA nuevo.

## 3. Despacho único de DOC_CLOSING

- [ ] 3.1 Limitar la API a registrar idempotentemente la respuesta y dejar elegible el mismo Run; hacer que el Scheduler despache DOC_CLOSING bajo el claim durable existente.
- [x] 3.2 Tras `ACCEPTED`, mostrar inmediatamente en la PWA que la respuesta fue recibida y qué etapa está pendiente; mostrar inicio efectivo solo cuando lo confirme el Run actualizado y conservar el gate si la API falla.
- [ ] 3.3 Verificar con API y Scheduler concurrentes contra PostgreSQL que una respuesta repetida o varios workers no generan una segunda invocación ni pierden la respuesta aceptada.

## 4. Gates accionables

- [ ] 4.1 Añadir al payload existente la evidencia afectada y el diff observable de tareas/requisitos cuando aplique, más explicaciones de acción y consecuencia para las opciones; preservar valores nativos, redacción y autorización.
- [x] 4.2 Hacer `diff`, `affected_items` y `option_explanations` opcionales de extremo a extremo y mostrarlos en la vista existente del gate sin cambiar el valor de respuesta; mantener funcionales los payloads históricos sin esos campos.

## 5. Verificación integrada

- [ ] 5.1 Ejecutar las pruebas pertinentes y un E2E real del flujo afectado con PostgreSQL y los procesos API/Scheduler separados; conservar evidencia de invocaciones, resultados, SHA del candidato y ausencia de despachos duplicados.
- [ ] 5.2 Ejecutar `openspec validate issue-460-stage-transition-robustness --strict --no-interactive` y comprobar los cinco criterios del Issue contra el mismo candidato inmutable.
