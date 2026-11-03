# Tasks

## 1. Registro y migración

- [x] 1.1 Añadir el modelo SQLAlchemy/UoW, repositorio e índice de identidad para `provider_model_registry`; verificar persistencia, unicidad y versionado con pruebas PostgreSQL.
- [x] 1.2 Crear la migración Alembic transaccional y backfill idempotente de entradas estáticas; verificar upgrade/downgrade sin tocar conexiones de proyecto ni secretos.
- [x] 1.3 Implementar DTOs allowlisted para proveedor, harness, modelo, capacidades y diagnóstico; verificar que tokens, claves y valores de credenciales no aparecen en serialización, logs ni errores.

## 2. Descubrimiento y diagnóstico

- [x] 2.1 Definir el contrato mínimo de introspección read-only y adaptadores para OpenCode, Ollama y harnesses configurados; la allowlist debe incluir, como ejemplos concretos, `opencode --version` y `opencode models` para OpenCode, y `ollama --version` y `ollama list` para Ollama, ejecutados como `argv` sin shell, con ejecutable resuelto desde configuración segura y sin argumentos adicionales; verificar con casos positivos que cada par produce diagnóstico/listado sin inferencia y con casos negativos que `opencode run ...`, `ollama run ...`, `sh -c ...`, redirecciones, pipes y cualquier argumento no listado se rechazan antes de crear el proceso, además de verificar timeout y rechazo de comandos arbitrarios.
- [x] 2.2 Implementar normalización, clasificación de origen y upsert que nunca sobrescriba un modelo custom con discovery; verificar refresh repetido e identidad separada de DeepSeek directo y namespace OpenCode.
- [x] 2.3 Implementar diagnóstico de CLI, versión, credencial, permiso y resultado por harness; verificar que ausencia, timeout, salida malformada o permiso insuficiente producen estado bloqueado/no disponible y no habilitan dispatch.

## 3. API administrativa

- [x] 3.1 Exponer `GET /api/v1/admin/providers/catalog` con autorización y composición de proveedores, harnesses, modelos y diagnóstico; verificar respuesta sin secretos y con entradas static/discovered/custom.
- [x] 3.2 Exponer `POST /api/v1/admin/providers/models` para alta/edición custom con canonicalización, contexto, origen y capacidades; verificar idempotencia por identidad, control de versión y rechazo de payload secreto.
- [x] 3.3 Conectar la operación de refresh al catálogo administrativo sin activar automáticamente ejecuciones, scheduler, despliegue ni mutaciones remotas; verificar que el efecto durable observable se limita al registro.

## 4. Perfiles y resolución

- [x] 4.1 Integrar la validación de los roles thinker, implementer, reviewer y backup con capacidades verificadas del catálogo mediante este algoritmo: resolver cada asignación por la identidad canónica `(provider_id, harness_id, canonical_model_id)`; rechazar si no existe una única fila viva, si `discovery_status` no es `available`, si `last_observed_at` supera la ventana de frescura configurada o si el diagnóstico/credencial no está verificado; exigir `read_only_review` para `reviewer`, `file_edit` y capacidad de ejecución del workflow para `implementer`, y las capacidades mínimas del workflow seleccionado para `thinker` y `backup`, sin inferir capabilities por nombre; evaluar las cuatro asignaciones independientemente, devolver el rol y capability faltante en el error, y solo persistir/despachar cuando todas pasen. Verificar con catálogo vivo y evidencia observable la aceptación de combinaciones compatibles, el rechazo de thinker sin capacidad de pensamiento/workflow, implementer sin `file_edit`, reviewer sin `read_only_review`, backup incompatible, modelo ausente, stale, bloqueado o con credencial no verificada, y confirmar que ningún caso rechazado persiste ni inicia dispatch.
- [x] 4.2 Hacer que la resolución del siguiente Run conserve exactamente provider, harness, model, effort y route seleccionados; verificar un Run de integración contra perfiles persistidos.
- [x] 4.3 Derivar `resolveAgentForModel`, `buildProfile` y `getRoleModel` de la entrada canónica y `model_routes`; verificar modelo custom, ruta desconocida y ausencia de inferencia por substring.
- [x] 4.4 Mantener funcionales todos los símbolos y aliases legacy exigidos y retirar solo mapeos demostrablemente muertos; verificar consumidores existentes, regresión de resolvers y evidencia de reemplazo antes de eliminar cualquier ruta.

## 5. Integración y evidencia

- [x] 5.1 Ejecutar una prueba E2E real con un harness disponible que observe invocación read-only, salida de CLI, fila persistida, respuesta del catálogo y resolución de perfil; conservar evidencia de cada efecto. [operator-accepted]
- [x] 5.2 Ejecutar E2E de fallo para CLI ausente/timeout, credencial inválida, reviewer sin solo lectura, implementer sin edición, payload secreto y actualización stale; verificar ausencia de dispatch o mutación no autorizada. [operator-accepted]
- [x] 5.3 Ejecutar pruebas de concurrencia y rollback de migración/refresh/custom update; verificar que no hay duplicados, lost updates, secretos persistidos ni pérdida de configuraciones existentes. [operator-accepted]
- [x] 5.4 Ejecutar la suite relevante de catálogo, perfiles, adaptadores, API y migraciones y revisar el diff para confirmar que no se creó una implementación paralela de OpenSpec ni se alteró la autoridad de despliegue; registrar resultados y SHA candidato. [operator-accepted]
