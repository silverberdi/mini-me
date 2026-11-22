## Context

Ver `proposal.md` y la delta de `execution-operations-dashboard`. El Dashboard y las vistas especializadas comparten `RefreshService`; la respuesta de Runs ya incluye `is_active`, `stage`, `status`, `change_name`, `request_id` y `project_id`. Trabajo Actual ya posee el orden de diez etapas, las ilustraciones y las clases visuales de etapa.

## Goals / Non-Goals

**Goals:**
- Presentar el Run activo del proyecto seleccionado y su avance de etapa de forma compacta y útil en móvil.
- Mantener una sola fuente para orden, etiquetas e ilustraciones de etapas, y aplicar en Dashboard las mismas clases de etapa que Trabajo Actual.
- Retirar las dos listas redundantes del Dashboard dentro del alcance del Issue.

**Non-Goals:**
- Cambiar API, PostgreSQL, contratos de Run/Request, selección de proyecto o cualquier vista especializada.
- Crear un porcentaje, un segundo estado de orquestación, acciones de ejecución o telemetría nueva.

## Decisions

1. **Consumir los datos ya cargados.** Seleccionar el Run marcado `is_active` en `refresh.runs()` para el proyecto seleccionado. Resolver el Request asociado por `request_id` entre los Requests ya cargados. Si falta ese Request, conservar el resumen del Run sin inventar sus datos. No agregar endpoints ni polling.
   - Alternativa descartada: agregar una lectura agregada o nuevos campos de API; no son necesarios con el modelo actual.
2. **Compartir la presentación de etapas con Trabajo Actual.** Extraer a un módulo pequeño de presentación la lista ordenada de etapas, sus etiquetas e ilustraciones, y las reglas visuales de etapa completada/actual/pendiente. Las dos vistas consumirán esa fuente para mostrar el mismo avance. El Dashboard la presentará como una fila compacta de diez indicadores, con nombres accesibles, debajo de la ilustración actual; no copiará una segunda lista de etapas.
   - Alternativa descartada: duplicar el mapeo y las clases en Dashboard, porque podrían divergir.
3. **Derivar el progreso solo de la etapa persistida.** Los indicadores previos a la etapa actual se muestran completados, la etapa actual resaltada y las siguientes pendientes, siguiendo la semántica visual existente. No calcular porcentaje. Si la etapa es desconocida, mostrar el valor recibido y estado, sin elegir ilustración ni inferir avance.
4. **Navegar con las rutas existentes.** El enlace activo abre `/trabajo-actual` con el `run` y `project` correspondientes. El estado sin Run enlaza a `/backlog`. Ningún control crea Run directamente.
5. **Diseñar primero para móvil.** La tarjeta combina nombre/Request, ilustración vigente, etapa/estado y franja de progreso en un flujo que puede envolver texto sin ensanchar la página. Los dos bloques antiguos de listas se eliminan del Dashboard; las vistas Trabajo y Backlog siguen siendo sus destinos de detalle.

## Risks / Trade-offs

- **El servidor no expone un porcentaje de avance:** mostrar solo progreso por etapa evita precisión ficticia y satisface el seguimiento visual solicitado.
- **Etapa desconocida o metadatos faltantes:** se conserva la información disponible y se omiten solo los elementos que no se pueden determinar; no se muestra una ilustración o progreso aproximado.
- **Cambio compartido de presentación:** extraer las reglas puede afectar Trabajo Actual; la regresión debe comprobar que sus etiquetas, colores e ilustraciones se mantienen iguales.

## Migration Plan

Sin migración de datos ni despliegue manual. El cambio modifica el frontend Angular entregado por el flujo CI/CD del proyecto. La ruta anterior de tarjetas se retira en el mismo cambio.
