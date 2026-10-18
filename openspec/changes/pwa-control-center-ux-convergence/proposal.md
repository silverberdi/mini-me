## Why

mini me ya sirve una PWA operacional, pero su superficie actual combina un dashboard legacy grande con un bootstrap modular y no expresa con suficiente claridad, de forma consistente y responsive, el estado real del trabajo ni las decisiones humanas que requieren atención. Este Change converge esa PWA existente en el centro de control aprobado por Stitch, reutilizando las APIs y autoridades actuales y mostrando incertidumbre explícitamente en lugar de convertir ilustraciones o datos ausentes en hechos.

## What Changes

- Moderniza el shell existente en español y sus vistas de Centro de Control, Backlog/Cola, Runs, Proyectos, Proveedores, Actividad y Métricas, siguiendo las ocho capturas y tres composiciones aprobadas.
- Unifica la lectura de RUNNING, pausa deliberada, espera de capacidad, recuperación, autenticación requerida, `NEEDS_HUMAN`, `UNKNOWN` y `READY_FOR_HUMAN_MERGE`; distingue la observación de solo lectura del servicio `minime-scheduler.service`, su habilitación de arranque y el modo lógico de admisión.
- Converge el detalle Run/Job en una vista contextual con pipeline, candidato, checks, review, actividad, GitHub, coste y acciones que el backend autorice dinámicamente.
- Entrega layouts de escritorio de alta densidad, tablet master-detail y móvil de supervisión/atención, conservando el shell PWA y los temas existentes con accesibilidad y degradación segura; el service worker conserva únicamente recursos estáticos seguros y nunca respuestas operacionales o autenticadas.
- Añade solo los campos/read-models de API que el censo demuestre imprescindibles para representar hechos reales; no añade autoridad de orquestación ni estado paralelo al cliente.
- Migra y retira dentro del Change los entrypoints/código de UI que efectivamente queden reemplazados, incluidos los dos controladores actuales `dashboard.js`/`app.js`, después de asignar un único propietario de refresco/listeners, demostrar paridad de cada consumidor y repetir las regresiones.

## Capabilities

### New Capabilities

Ninguna. El resultado extiende la PWA y el read model operacional ya existentes.

### Modified Capabilities

- `pwa-app-shell-and-queue`: shell, navegación y cola deben expresar estados y razones con datos autoritativos y lenguaje visual convergente.
- `pwa-runs-and-pipeline-observability`: detalle Run/Job y evidencia deben ser candidate-bound, comprensibles y coherentes entre las vistas.
- `pwa-preview-and-operator-actions`: atención humana, preview y mutaciones deben respetar discovery, permisos y confirmación del Control Plane.
- `pwa-responsive-and-offline-pwa`: define el comportamiento responsive, accesible y de solo lectura durante degradación/offline.
- `execution-operations-dashboard`: exige que las proyecciones disponibles para la PWA distingan estados y procedencia reales, incluido `UNKNOWN` cuando el backend no provea evidencia.

## Impact

Impacta `src/minime/static/index.html`, `src/minime/static/js/`, `src/minime/static/css/`, PWA manifest/service worker y, únicamente si se demuestra una laguna de datos, los read models/endpoints FastAPI existentes en `src/minime/api/app.py` y `src/minime/services/dashboard_service.py`. Afecta pruebas API, estáticas y de navegador de dashboard/PWA. Reutiliza `/api/v1/dashboard/*`, `/api/v1/orchestration/runs`, `/api/v1/queue`, `/api/v1/scheduler/status`, `/providers/health`, `/budget/usage`, eficiencia, acciones del Control Plane, previews, validaciones y `/api/v1/auth/me`, sujetos a verificación de sus esquemas y middleware. No requiere de antemano una migración de base de datos, framework frontend nuevo ni cambio de políticas de admisión/proveedor.

No-goals: segunda aplicación/dashboard, chat de agentes, orquestación en el browser, acceso directo a PostgreSQL, invocación de CLI/Git/systemd/proveedores desde el cliente, cambios de política de scheduler/cuotas, telemetría ficticia, reanudación impulsiva en móvil, auto-merge o sustitución del TUI.

Dependencias de secuencia: implementar después de las capacidades MM-R03–MM-R06 indicadas por `docs/backlog/MM-R07.md`, una vez que los contratos de read model y acciones que este Control Center presentará sean estables. La propuesta no modifica ni amplía el Change R01 actualmente en curso, que excluye explícitamente el rediseño del dashboard.
