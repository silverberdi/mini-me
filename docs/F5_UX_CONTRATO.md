# F5 — Contrato funcional de la interfaz visual (refinamiento del operador)

**Fecha de decisión:** 2026-10-26. **Autoridad:** decisión expresa del operador durante el refinamiento previo a F5; complemento del [Contrato rector](CONTRATO_RECTOR.md), [Issue F5 #173](https://github.com/silverberdi/mini-me/issues/173) y antecedente UX [#162](https://github.com/silverberdi/mini-me/issues/162). Este documento **no es un Change OpenSpec**, no crea ni ejecuta `gacela-05-ui-self-hosted` y no sustituye los workflows nativos.

## 1. Alcance y fronteras

- **F5 es un MVP visual y primera autoejecución auténtica:** reimplementar la UI española de mini me mediante **HTML, JavaScript nativo modular y Tailwind CSS**, conservando **FastAPI y PWA**, con temas claro/oscuro y responsive web/tablet/móvil. No adoptar Angular/React ni trasladar reglas de ejecución al cliente. Tailwind se compila/se sirve localmente; sin dependencia de CDN de producción.
- **Cinco vistas independientes** con rutas y navegación real, pero **solo dos destinos primarios:** `Dashboard` y `Proyectos`. Desde Dashboard se accede a `Trabajo` y `Trabajo actual`; desde el detalle de Proyectos se accede a `Backlog`. Admite enlaces profundos y navegación atrás/adelante. No apilar las cinco vistas en Home.
- **Sin nuevas funciones de orquestación en F5.** Reusar API, read models, acciones reales, autenticación y gates existentes; solo se habilita una acción si el backend la soporta y autoriza. Los controles de capacidades nuevas diseñados ahora se incluyen en su ubicación visual, pero quedan **deshabilitados con explicación explícita «Disponible en F7»** hasta tener respaldo real. Nada de diálogos que fingen confirmación, mutaciones ficticias, estados inventados o métricas simuladas en producción.
- La fuente de Requests es el **proveedor de tickets configurado por proyecto** (GitHub inicialmente). Proveedor de tickets y Git/PR son contratos separados. No acoplar formularios, navegación, modelo ni nombres internos a GitHub; mostrar links al origen remoto cuando existan.
- La ejecución de F5 debe ser materialmente realizada por **mini me sobre sí mismo** usando sus agentes y OpenSpec nativo, sin circularidad con la UI por terminar: arranque por CLI/API existente, auténtico E2E y las autorizaciones pertinentes. La corrección excepcional de bootstrap PR #188 es un gate previo, **no autoriza** fusionarlo ni desplegar, gastar cuota, encender scheduler ni iniciar F5.

## 2. Disposición y navegación

| Vista | Acceso | Objetivo y composición |
| --- | --- | --- |
| **Dashboard** | Principal | Estado y rendimiento del único **proyecto que tenga el foco operativo**, trabajo actual, avance, cuotas por modelo, efectividad, atención humana y salud compacta. |
| **Trabajo** | Dashboard | Secuencia **Último terminado → En ejecución → Siguiente**, cada uno con enlace a su contexto; sin lista extensa de Backlog. |
| **Trabajo actual** | Dashboard o Trabajo/Backlog contextual | Seguimiento del progreso OpenSpec por etapas y tareas, hechos/artefactos/timestamps reales, salidas verificadas y **HUMAN_REQUIRED** in situ. No narración especulativa de pensamientos del agente. |
| **Proyectos** | Principal | Lista a la izquierda y detalle seleccionado a la derecha en web/tablet (móvil navega a detalle), configuración F2, roles/modelos, contratos de proveedores, contexto documental, estado y acceso a Backlog. |
| **Backlog** | Proyecto seleccionado | Pestañas **Pendientes** (FIFO/elegibilidad autoritativa) y **Terminados** (cierre real más reciente primero), detalle contextual; controles visuales de gestión de Requests. |

`Trabajo`, `Trabajo actual` y `Backlog` siguen siendo **vistas completas**, no tabs dentro del Home ni paneles apilados.

## 3. Dashboard — Instrumentación operacional simple

**Protagonista:** el proyecto seleccionado/en foco para ejecución y su Request actual; **no presentar simultaneidad multiproyecto como capacidad probada**. Si no existe selector único global todavía, distinguir explícitamente configuración F2 `ACTIVE/PAUSED` de la futura autoridad de proyecto ejecutor (F7). No fabricarlo.

- **Medidor analógico de avance del proyecto:** progreso comprobable y denominador definido (p. ej. Requests completados frente a un objetivo observable). Sin denominador válido, indicar `No disponible` en vez de 0 % o porcentaje calculado artificialmente.
- **Medidor analógico de avance del Request/tarea actual:** cantidad verificada de tareas/hitos aplicables, etapa OpenSpec y acceso directo a `Trabajo actual`. Distinguir Request total de tarea en ejecución; si no existe autoridad fiable, mostrar estado real y dato no disponible.
- **Medidores analógicos de cuota por modelo:** proveedor/modelo, cuota usada/restante, período y fecha de renovación **solo si el proveedor ofrece límites verificables**. Si solo existen tokens/costo, mostrar esas cifras con su unidad, sin llamarlas porcentaje de cuota. No atribuir consumo al modelo default sin evidencia.
- **Gráfica de líneas de efectividad por Request finalizado**, con tres dimensiones **seleccionables y escalas independientes**, no sumar cantidades incompatibles:
  1. **Calidad/autonomía:** iteraciones/ciclos Apply–Verify–Review, correcciones, aclaraciones humanas evitables frente a autorizaciones/gates obligatorios; no penalizar acuses normativos como si fueran fallos.
  2. **Tiempo:** duración total, tiempo efectivo y tiempos de espera/pausa cuando existan timestamps verificables.
  3. **Recursos IA:** tokens/costo por Request y modelo cuando sean atribuibles y medidos; cuota restante solo si la fuente la publica.
  Comparar secuencias de Requests terminados (p. ej. últimas 5/10/20) cuando haya datos suficientes. Indicadores sin instrumentación disponible se ven como `Pendiente de datos — F7`, no valores de ejemplo.
- **Atención y salud operativa discretas:** banner/bandeja de gates reales con enlace a stage `HUMAN_REQUIRED` y resumen de salud API/DB/scheduler/proveedores según lecturas reales. `WAITING_CAPACITY` y `UNKNOWN` no equivalen a `HUMAN_REQUIRED`. El scheduler productivo deshabilitado se describe fielmente.

**Control visual global `Pausar mini me`:** representa pausa **diferida** tras terminar el Change actual (o inmediata si ya está inactivo), sin interrumpir etapas/agentes. Hasta que exista autoridad F7, visible pero **no accionable**; la pausa administrativa de proyecto F2 no se anuncia como equivalente.

## 4. Trabajo

Composición simple de **tres momentos**: último Request completado con resultado y evidencias; trabajo en ejecución con etapa/estado y enlace a `Trabajo actual`; siguiente Request elegible real con dependencia y orden remoto. Si alguno falta, mostrar un estado vacío verdadero. Web puede presentar los dos últimos como tarjetas lado a lado; móvil apila. No crea operaciones de reordenamiento/selección manual del backlog.

## 5. Trabajo actual y solicitudes humanas

- Cabecera con proyecto, ID Request/ticket, Change OpenSpec, Run/candidato y estado **reales**.
- Seguimiento visual de flujo real por stages OpenSpec y progreso de tareas respaldado por evidencia: completado, ejecutando, pendiente, bloqueado, espera, fallido, desconocido. Por etapa se consulta el resumen, resultados, agente/modelo realmente utilizado y tiempos observables; documentación/logs técnicos quedan en detalle opcional. **No inferir qué piensa el agente.**
- **HUMAN_REQUIRED llega y se resuelve aquí:** mostrar pregunta literal/contexto, opciones originales vs propuestas claramente etiquetadas, consecuencias, permisos/acciones realmente disponibles, respuesta o acuse conforme al backend. Si hay varias, lista ordenada; sin modales consecutivos invasivos. Deben seguir visibles hasta resolución durable, aun si la PWA se cierra o actualiza. Dashboard solo notifica y enlaza a este lugar.
- Continuación únicamente si API/Control Plane confirma la resolución y los gates vigentes la permiten. Nunca permitir edición libre de un Request admitido; una aclaración aprobada se tramita por HUMAN_REQUIRED.

## 6. Proyectos

Lista + detalle. Mostrar nombre/ID, repositorio, tipo, onboarding y estado F2 reales; configurar/consultar perfiles de pensamiento, ejecución, revisión independiente y fallback permitido, modelo, conexión de tickets y Git/PR separados. Mostrar índice de contexto y documentos autorizados. Consulta y operaciones F2 existentes pueden estar activas; cualquier **edición documental persistente** ausente debe disponer de UI de lectura/editor/diff/guardar/cancelar **deshabilitada honestamente** hasta la ruta segura, versionada y gobernada de F7 (no escritura arbitraria del navegador).

**Control visual `Pausar proyecto`:** pausa **diferida** después del Change completo (PR1/PR2/cierre) sin cancelar el trabajo activo; si inactivo pausa inmediata. Estado visual `Activo`, `Pausa pendiente`, `Pausado` **solo cuando exista autoridad real**. Por ahora no conectar la simple bandera F2 a esta promesa operativa.

**Selección del único proyecto ejecutor:** en F7; en F5 mostrar el concepto/ubicación visual no funcional y separar `proyecto configurado` de `proyecto ejecutando`. F7 cambiará de proyecto tras cierre seguro del Change actual, sin simultaneidad ni preempción.

## 7. Backlog y futuro formulario de Request

- Dos pestañas: `Pendiente` por FIFO/elegibilidad y `Terminado` por hora real de terminación descendente; diferenciar activo/bloqueado/desactivado/cancelado sin inventar resultados. Detalle con cuerpo del ticket, criterios, dependencias, trazas OpenSpec, historial/PR y enlaces al proveedor remoto.
- **Controles visuales obligatorios en F5**, aunque deshabilitados hasta F7 si no existe API apta: `+ Nuevo Request`, `Editar`, `Desactivar`/`Reactivar`, `Eliminar lógicamente`. Deben tener confirmación/contexto y explicar por qué están indisponibles, **no reemplazar el formulario propio por un simple link a GitHub**.
- Formulario `Nuevo Request`: **título, descripción y criterios de aceptación obligatorios** en lenguaje natural; **no exigir Gherkin a la persona**. El proveedor de tickets configurado es el autoritativo, no una réplica PostgreSQL.
- **Matriz de acciones para F7**:
  - **No iniciado** (sin admisión durable): crear, editar, desactivar, reactivar si desactivado, eliminar lógicamente.
  - **En curso/admitido**: no edición libre, no desactivación ni eliminación; aclaración/cambio contextual solo por `HUMAN_REQUIRED` y gobernanza existente.
  - **Finalizado**: no editar/desactivar/eliminar.
  - **Eliminado lógicamente**: conservar registro/evidencia/trazabilidad, fuera del Backlog operativo; **jamás borrar físicamente** el Request remoto.
- F7 conecta proveedor configurable, control de estados, idempotencia, seguridad, historial y operaciones; reusa la **normalización F4 previa a Explore** que transforma criterios humanos a Gherkin Given/When/Then, conserva literalmente el cuerpo original en comentario de procedencia y eleva ambigüedades materiales. No duplicar esa capacidad.

## 8. Adaptación a dispositivos y experiencia

- **Web:** centro de control con uso eficiente del viewport, medidores legibles, panel contextual cuando aporte valor, sin scroll global gigante ni grandes vacíos.
- **Tablet:** maestro/detalle táctil, navegación real y operaciones autorizadas soportadas.
- **Móvil:** las mismas cinco vistas accesibles mediante rutas enfocadas, observabilidad rápida y resolución de decisiones sencillas; los controles sin backend se explican como no disponibles en **todos** los dispositivos. No afirmar paridad de mutaciones faltantes ni eliminar rutas.
- Idioma español, lectura de pantalla, teclado, foco, contraste, objetivos táctiles, zoom/reflow, estados de error/carga/offline, contenido autenticado no cacheado. Conservar identidad visual aprobada de Stitch/#162 **donde no contradiga decisiones posteriores expresas**.

## 9. Límite F5 / F6 / F7 / F8 y criterios observables

- **F5:** todo lo visual precedente; operaciones existentes reales, nuevas capacidades solo representadas y etiquetadas deshabilitadas; Tailwind + JS nativo + FastAPI PWA; E2E navegador y **autoejecución real por mini me**. Un solo Change F5 `gacela-05-ui-self-hosted`.
- **F6:** depuración/retirada segura ya aprobada, ejecutada por mini me; no se amplía a F7.
- **F7 [#189](https://github.com/silverberdi/mini-me/issues/189):** implementar las capacidades funcionales diferidas: pausa global/proyecto al fin del Change, proyecto ejecutor único, crear/editar/desactivar/reactivar/eliminar **lógicamente** Requests bajo reglas anteriores, conectar normalización F4 y métricas/instrumentación faltantes, edición documental segura si falta. Está **disabled**, sin Change ni autorización de ejecución.
- **F8 [#190](https://github.com/silverberdi/mini-me/issues/190):** migración de la **capa visual** a Angular + TypeScript + Tailwind, sin reemplazar FastAPI ni orquestador, previa verificación de paridad; está **disabled**, sin Change ni autorización.
- **Secuencia y seguridad:** F1–F6 preservan el ciclo original de reconstrucción con sus Changes; F7–F8 se añaden como fases posteriores, no reabren ni reescriben F1–F4. Sin split en micro-Changes, cambios de scope no autorizados, scheduler habilitado, nuevas llamadas a agentes, merge o deploy por esta documentación.

**Aceptación mínima F5:** rutas reales para 5 vistas con 2 destinos primarios; medidores visibles con estados no medidos honestos; 3 dimensiones de efectividad con gráficas vacías justificadas si faltan datos; Trabajo en 3 momentos; navegación contextual por stage y HUMAN_REQUIRED real; lista/detalle de Proyectos y Backlog en 2 tabs; formularios/controles F7 visuales pero **deshabilitados sin fingir ejecución**; autenticación y seguridad; Tailwind local; E2E navegador responsive; evidencia de autonomía real con 2 PR y cierre OpenSpec según reglas.

**Prevalencia:** este refinamiento del operador resuelve en el alcance de F5 las contradicciones de navegación, activación de funciones y framework con el antecedente #162 y documentos históricos. El contrato rector vigente mantiene autoridad; actualizarlo conjuntamente antes de admitir F5.