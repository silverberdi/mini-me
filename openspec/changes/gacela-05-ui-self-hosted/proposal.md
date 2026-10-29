# Proposal

## Why

El operador necesita una consola española que permita observar trabajo real y resolver atención humana desde web, tablet y móvil. F5 sustituye la carcasa transitoria de F1 y debe demostrar que mini me puede ejecutar su propio Change completo, sin convertir una propuesta o un reporte histórico en evidencia de ejecución.

## What Changes

- **BREAKING (navegación heredada):** cinco vistas independientes con enlaces profundos, atrás/adelante y solo Dashboard/Proyectos como destinos principales; Trabajo y Trabajo actual se abren desde Dashboard y Backlog desde el proyecto seleccionado.
- HTML, JavaScript nativo modular y Tailwind compilado localmente sobre FastAPI/PWA existentes; español, temas claro/oscuro y accesibilidad responsive.
- Dashboard con medidores analógicos, tres dimensiones de efectividad, atención y salud compactas. Porcentajes exclusivamente con fuente y denominador verificables; estados sin datos explícitos.
- Trabajo presenta último terminado → en ejecución → siguiente; Trabajo actual presenta hechos, etapas, tareas, modelos, tiempos y evidencia del candidato, sin narrar pensamientos.
- HUMAN_REQUIRED persistente y respondible exclusivamente mediante autoridad backend vigente; Dashboard notifica y enlaza. No degradar este requisito a un formulario simulado.
- Proyectos muestra lista/detalle, configuración F2 y conexiones separadas; Backlog mantiene la fuente remota autoritativa, FIFO y terminados por cierre descendente.
- Formulario visual de Nuevo Request, gestión lógica de Requests, pausa diferida, selector de ejecutor y editor documental visualmente presentes pero deshabilitados con explicación F7 donde falte autoridad. Sin backend CRUD, instrumentación nueva, scheduler ni estado paralelo.
- Retirar únicamente la UI transitoria y consumidores sustituidos dentro de F5; conservar autenticación, PWA, historias, migraciones y workflows oficiales.
- Exigir E2E auténtico responsive y trazabilidad de la autoejecución por mini me hasta PR1, Sync/Archive nativos, PR2 y cierre remoto. F6 conserva su alcance; F7/F8 siguen disabled.

## Capabilities

### New Capabilities

- `f5-projects-and-backlog`: Proyectos, contexto y Backlog remoto con controles futuros honestos y matriz de acciones por estado.
- `f5-self-hosted-delivery`: aceptación específica de F5 mediante navegador real, validación humana y autoejecución observable de este mismo Change.

### Modified Capabilities

- `pwa-app-shell-and-queue`: cinco rutas, dos accesos principales, Dashboard verificable y eliminación de ranking/cola visual heredada.
- `pwa-runs-and-pipeline-observability`: Trabajo, Trabajo actual, etapas y evidencia reales, atención contextual y sin auditor obligatorio fijo.
- `pwa-preview-and-operator-actions`: decisiones confirmadas por backend, sin éxito optimista, bypass ni acciones heredadas presumidas funcionales.
- `pwa-responsive-and-offline-pwa`: composición por dispositivo y caché exclusivamente de recursos estáticos públicos.

## Impact

Superficie prevista: `src/minime/static/index.html`, `static/js/app.js`, `dashboard.js`, módulos de vistas/cliente, CSS/Tailwind local, `sw.js`, rutas de shell en `src/minime/api/app.py` y pruebas de UI/PWA. No cambios de esquema PostgreSQL ni nuevas APIs de negocio; una sola API y bootstrap/refresh.

Base inspeccionada: `84f1d6a6d7e0358cc960e6e26198667b9dd7c085`, rama/worktree de Request #173. Contrato rector v1.3 y `docs/F5_UX_CONTRATO.md` prevalecen sobre referencias v1.2 aún presentes en README/config y sobre #162. El CLI confirma raíz local y Change único; no se modifican Changes históricos.

**Brecha previa a Apply:** Dashboard, eficiencia y Control Plane heredados devuelven 410; Requests lista solo elegibles abiertos; la disponibilidad general de HUMAN_REQUIRED, terminados e instrumentación no está demostrada. El endpoint `/requests/ack` no equivale a resolución general. Se solicita decisión humana sobre esta incompatibilidad; el diseño conserva aceptación y marca Apply bloqueado hasta demostrar cobertura vigente o revisar alcance por OpenSpec Update autorizado. La propuesta no autoriza rehabilitar backend retirado.

**Complejidad propuesta: alta**, por cinco vistas, seguridad de decisiones, paridad responsive, retirada de UI y aceptación de autoejecución con dos PR. Requiere clasificación del coordinador y revisión independiente de propuesta y código sobre SHA inmutable; esta autoría no acredita esas revisiones.

La solicitud actual autoriza planificación solamente. El historial de #173 aportado (F4, bootstrap #188/#191, fallo de normalización y candidato Draft #192) conserva su procedencia de reporte; no acredita gates superados, continuación del Run, llamadas medidas, merge ni despliegue actuales.
