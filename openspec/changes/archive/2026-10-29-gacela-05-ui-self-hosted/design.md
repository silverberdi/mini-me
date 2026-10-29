# Design

## Context

La motivación y el alcance están en `proposal.md`; las seis delta specs de este Change definen el comportamiento observable. Este diseño conserva esos archivos. La autoridad funcional es el contrato rector v1.3 y `docs/F5_UX_CONTRATO.md`; las menciones v1.2 de README/config y la navegación histórica #162 no prevalecen.

Inspección local sobre HEAD `84f1d6a6d7e0358cc960e6e26198667b9dd7c085`, sin inspección del runtime o PostgreSQL productivos:

- `src/minime/static/index.html` conserva login Google y contenedor autenticado; `js/app.js` hace un único bootstrap y `js/dashboard.js` únicamente consulta `/api/v1/auth/me` y muestra la transición F1.
- `src/minime/api/app.py` sirve el shell en `/` y `/dashboard`, y recursos en `/static`. Agregar rutas de presentación no requiere otra API.
- Existen lecturas F2 de proyectos, onboarding y contexto. `/api/v1/projects/{project_id}/requests` devuelve `eligible_requests`, exclusivamente abiertos elegibles; no acredita cobertura de todos los pendientes ni terminados.
- `/api/v1/orchestration/runs` lista registros mediante `model_dump()`, pero no demuestra que cada campo sea apto para exposición visual ni que exista detalle completo de etapas. El detalle de estado heredado, Dashboard y Control Plane devuelven 410.
- `/api/v1/projects/{project_id}/requests/ack` es un acuse de merge para alta complejidad que invoca el coordinador; no es una operación general de respuesta a preguntas ni una lectura segura. No se usará para descubrir capacidades.
- `sw.js` ya restringe caché a un allowlist público y limpia versiones propias. Las pruebas `test_pwa_assets.py` y `test_pwa_service_worker.py` comprueban esa carcasa, no aceptación F5.

La brecha de HUMAN_REQUIRED registrada en la propuesta sigue abierta. Este documento fija la arquitectura visual y sus límites, pero no acredita autoridad general para responder ni habilita Apply. No se resuelve la incompatibilidad agregando backend F7 o sustituyendo la integración requerida por controles deshabilitados.

## Goals / Non-Goals

**Goals:** separar las cinco vistas mediante rutas reales; compartir sesión, lecturas y actualización; representar origen, cobertura y antigüedad de cada dato; mantener decisiones bajo autoridad backend; sustituir la UI transitoria sin duplicar frontend ni persistencia operativa.

**Non-Goals:** implementar APIs faltantes, instrumentación, CRUD de Requests, selección global de ejecutor, pausa diferida, scheduler, normalización alternativa o migraciones PostgreSQL. No se implementan Angular/TypeScript, motores de workflows ni despliegue productivo. La planificación no reanuda el Run histórico ni prueba sus reportes.

## Decisions

### 1. Shell único con rutas explícitas y módulos de vista

Usar ES modules nativos: `app.js` conserva el bootstrap; un router pequeño administra History API; un cliente concentra HTTP/sesión; un controlador de actualización concentra ciclo y cancelación; cada vista renderiza solo su área activa. Extraer componentes únicamente cuando haya consumidores reales. Evitar un controlador gigante o un framework propio de componentes.

| Vista | Ruta de presentación prevista | Entrada contextual |
| --- | --- | --- |
| Dashboard | `/dashboard` (`/` es entrada equivalente) | Principal |
| Trabajo | `/trabajo?project=<id>` | Dashboard |
| Trabajo actual | `/trabajo-actual?project=<id>&run=<id>&stage=<id>` | Dashboard / Trabajo |
| Proyectos | `/proyectos?project=<id>` | Principal; detalle seleccionado |
| Backlog | `/backlog?project=<id>&tab=<pendientes|terminados>&request=<id>` | Detalle del proyecto |

Solo las cinco rutas de shell explícitas se sirven desde FastAPI con GET/HEAD; no usar un catch-all que capture APIs, estáticos o rutas inexistentes. Recarga y `popstate` restauran contexto validado, sin seleccionar silenciosamente otro Run ante 403/404. Cambiar proyecto enfocado es navegación de observación, no asignación del ejecutor.

Alternativas: cinco pantallas apiladas contradicen el contrato; rutas solo hash no aprovechan las rutas reales del servidor; múltiples aplicaciones duplicarían autenticación y refresco. React/Angular quedan fuera del stack autorizado.

### 2. Una sesión y un ciclo de lecturas, sin nuevo bootstrap backend

El bootstrap consulta sesión y después carga lecturas necesarias para el contexto activo. Un solo ciclo ofrece actualización manual y 5/10/30 segundos; cambiar intervalo provoca lectura inmediata, cancela respuestas obsoletas y reemplaza el temporizador. Navegar desmonta listeners de la vista anterior; ninguna vista inicia su propio polling. Evitar solapamientos y descartar respuestas pertenecientes a otro proyecto/Run o generación de navegación.

Usar credenciales same-origin y `cache: no-store` en lecturas operativas. Mantener resultados solo en memoria; 401 limpia contenido autenticado, 403 muestra restricción y 410 ausencia de capacidad. Fallo de una fuente no convierte cobertura parcial en un resultado vacío completo. Exponer fecha de observación y estado desactualizado; no adjudicar un timestamp de evento a la hora del fetch.

Alternativas: un nuevo endpoint agregador ampliaría backend; refrescos por componente duplicarían tráfico y permitirían mezclar identidades. No se introducen stores persistentes ni suscripciones/eventos ficticios.

### 3. Mapa de capacidades fundamentado en las APIs existentes

El cliente transforma exclusivamente campos verificados a datos de presentación, con identidad, origen, unidad, cobertura y fecha. No descubre autoridad probando mutaciones ni depende de un endpoint de capacidades inventado. Antes de conectar una acción se verifica su contrato, permisos y vínculo al candidato; ausencia de esa evidencia mantiene el control inactivo.

| Superficie | Reutilización prevista | Límite comprobado / tratamiento |
| --- | --- | --- |
| Sesión | auth/me, login y logout existentes | Nunca almacenar credenciales o respuestas en caché |
| Proyectos | Lecturas F2 de lista, detalle, onboarding, contexto | Mostrar campos autorizados, sin secretos; F2 ACTIVE/PAUSED se etiqueta administrativo |
| Backlog | Lectura remota de requests elegibles | Declarar cobertura parcial; Terminados no disponible sin fuente real |
| Trabajo / Trabajo actual | Lista real de Runs y campos documentados | Stage no prueba finalización anterior; detalle faltante queda identificado |
| Dashboard | Fuentes reales de salud, uso y trabajo que se verifiquen | No llamar endpoints Dashboard retirados; no convertir presupuesto OpenRouter en cuota de suscripción |
| HUMAN_REQUIRED | Solo contrato vigente demostrado para pregunta y decisión | Control Plane 410 y requests/ack no cubren respuesta general; gate bloqueante |
| Contexto documental | Índice y enlaces autorizados F2 | Sin fetch arbitrario de archivos ni escritura directa |

No agregar tablas, repositorios de backlog ni lectura directa del filesystem desde el navegador. Formularios y nombres de UI usan Request/proveedor de tickets, independientemente de GitHub. Los enlaces remotos se validan por esquema y destino permitido; cuerpos y preguntas se renderizan como texto seguro, no HTML ejecutable.

### 4. Composición visual y datos honestos

Conservar marca, recursos e identidad existentes y referencias aprobadas de Stitch/#162 donde no contradigan el refinamiento. Compilar Tailwind mediante herramienta de build con versión fijada y lockfile; servir CSS resultante localmente. El artefacto desplegable incluye ese CSS; no compila ni descarga dependencias al abrir la PWA. Reutilizar tokens útiles de color/espaciado, retirando reglas antiguas solo tras censar consumidores.

Wireframes de composición:

- Dashboard: cabecera de proyecto en foco; medidores proyecto / Request / cuota; selector de dimensión y gráfica de efectividad; atención y salud compactas; enlaces Trabajo y Trabajo actual. Pausar mini me visible con explicación F7.
- Trabajo: Último terminado → En ejecución → Siguiente trabajo; cada momento contiene solo hechos y enlaces. En móvil se apilan estos tres momentos, no las cinco vistas.
- Trabajo actual: identidad y estado; etapas seleccionables; resultado/evidencia del stage; atención humana persistente en la misma vista. Logs técnicos se abren como detalle opcional.
- Proyectos: lista y detalle en escritorio/tablet; móvil navega al detalle con retorno explícito. Configuración, conexiones separadas, roles, documentos y enlace Backlog. Selector de ejecutor y pausa futura diferenciados de administración F2.
- Backlog: Pendientes/Terminados y detalle contextual; acceso a formulario visual de tres campos obligatorios y menú de gestión. Puede abrirse el formulario para inspección; envío y mutaciones sin autoridad permanecen deshabilitados con motivo F7. Finalizados inmutables; admitidos solo cambian por HUMAN_REQUIRED autorizado; nunca eliminación física.

Los medidores pueden usar SVG/CSS con texto equivalente: únicamente un numerador y denominador verificables dibujan porcentaje. Sin datos se mantiene el marco con No disponible, sin arco que aparente cero. Gráficas de líneas separan unidades y muestran huecos/explicaciones, nunca puntos de ejemplo ni interpolación de datos ausentes. ACTIVE no implica ejecutor; capacidades CLI no implican saldo de cuota; UNKNOWN no implica uso cero.

Usar landmarks, un título principal por vista, foco visible al navegar, etiquetas y descripciones de controles deshabilitados siempre legibles, y retorno del foco al cerrar diálogos. Tema claro/oscuro y reflow 200–400 % se verifican. Solo preferencias visuales no operativas pueden persistirse localmente.

### 5. Decisión humana confirmada por backend

El flujo requerido es lectura durable de pregunta/contexto → respuesta explícita autorizada → envío único → resultado backend → nueva lectura de autoridad. Conservar literal y opciones originales, separando sugerencias del agente. No ocultar la pregunta durante envío, rechazo o resultado incierto; no mostrar continuación por el mero éxito HTTP. Bloquear envíos duplicados locales y no reintentar automáticamente una mutación tras timeout. Confirmar efectos relevantes de forma accesible; un diálogo no crea autorización.

Sin una API real que cubra ese flujo, mostrar el bloqueo y conservar identidad/contexto observable. Esa representación no satisface la aceptación HUMAN_REQUIRED. Quedan prohibidos el uso de requests/run como refresco, requests/ack como respuesta genérica o ejecución de Git/CLI/agentes desde el navegador.

### 6. PWA y retirada dentro del Change

Conservar manifest y registro SW; actualizar versión y allowlist al grafo completo de módulos/CSS vivos. Solo shell público está cacheado. Navegación offline recupera shell sin almacenar URL con cuerpos o decisiones; datos retenidos en memoria se marcan obsoletos, mutaciones se bloquean y reconectar refresca autoridad antes de habilitarlas. Logout borra memoria autenticada. No hay cola de respuestas offline.

Retirar el panel transitorio `showReadOnlyTransition`, sus listeners/imports y CSS sin consumidores una vez sustituido. Actualizar pruebas que hoy exigen exactamente dos módulos JS; preservar sus garantías de sesión y caché. No borrar pruebas útiles para obtener verde, rutas backend históricas o tablas ajenas a F5. El inventario de consumidores previo al retiro decide qué tokens/CSS se conservan.

### 7. Verificación y límites de evidencia

Pruebas de router, refresh, procedencia de métricas, rechazos y SW verifican contratos locales. El E2E se ejecuta posteriormente con navegador real contra candidato y servicios aislados autorizados, sin presentar mocks como integración. Registrar comando, resultado, screenshots, identidades y efectos antes/después; usar desktop 1440×900 y 1920×1080, tablet 1024×768 y 768×1024, móvil 390×844 y 360×800.

Cubrir enlaces profundos/atrás/adelante, dos destinos primarios, teclado/foco/tema/reflow, vacíos parciales, stale/offline, 401/403/410/conflicto/timeout, controles F7 sin llamadas de mutación y HUMAN_REQUIRED real hasta decisión durable. Validación humana describe precondiciones, acciones y resultado esperado por vista/dispositivo, ligada a head/base SHA y digest si existe. Un candidato nuevo invalida la certificación anterior. La revisión independiente compara ese SHA con specs, código y evidencia; no la certifica esta autoría.

La prueba de autoejecución es distinta del E2E visual: mini me debe vincular mismo Request/Change/Run/worktree a workflows y agentes reales, PR1 y su política de merge, Sync/Archive nativos en rama documental fresca, PR2, cierre remoto posterior y liberación durable. No sustituirlo por prompts manuales ni inventar evidencia futura. Conservar usage UNKNOWN como tal y autorizaciones por objeto; no iniciar F6.

## Risks / Trade-offs

- [HUMAN_REQUIRED sin autoridad general demostrada] → Apply y aceptación permanecen bloqueados. Resolver mediante evidencia de cobertura vigente o decisión humana material seguida de OpenSpec Update; no construir silenciosamente backend fuera de alcance.
- [Requests solo elegibles y endpoints históricos retirados] → Declarar cobertura parcial y ausencia de detalle/terminados; no presentar una cola completa ni read models inventados.
- [Mezclar lecturas o decisiones entre candidatos] → Identidad explícita, descarte de respuestas tardías, refresco de autoridad y rechazo de validación obsoleta.
- [Pérdida de identidad visual histórica] → Comparación humana de wireframes/candidato con referencias aprobadas antes de Apply cuando haya discrepancia material; este documento no afirma validación visual.
- [Refactor visual rompe caché/imports] → Actualizar conjuntamente allowlist, build CSS y pruebas de grafo; verificar navegación offline y logout.
- [Mocks o reportes históricos parecen aceptación] → Separar evidencia local, integración real, revisión independiente y resultados humanos; falla cerrada ante cualquier ausencia.

## Migration Plan

1. Antes de Apply, resolver el gate material de autoridad y diseño/paridad pendiente; completar tasks nativas y revisión de propuesta de alta complejidad según clasificación del coordinador. Sin esas condiciones la implementación no queda autorizada por este diseño.
2. En Apply autorizado, cambiar shell, rutas de presentación, módulos y CSS en este mismo Change; retirar consumidores transitorios tras comprobar paridad. No hay migración de DB prevista ni despliegue productivo dentro de mini me.
3. Verificar build reproducible, pruebas pertinentes y E2E real sobre candidato congelado. Obtener revisión independiente y validación humana vigentes. Preparar PR1 conforme al contrato sin cierre automático del Issue.
4. Tras merge confirmado de PR1, usar workflows Sync/Archive oficiales desde rama documental fresca y PR2; cerrar remoto solo tras segundo merge. Despliegue pertenece al CI/CD del proyecto bajo sus propias autorizaciones.
5. Ante fallo previo al merge, corregir candidato por workflow nativo conservando evidencia; para reversión posterior usar revert revisable y nuevo identificador de caché que retire recursos incompatibles. No reset duro ni cambio de DB para revertir una entrega visual. Ninguno de estos pasos se ejecuta al redactar este archivo.
