# Backlog vigente — mini me Gacela

**Autoridad:** [Contrato rector v1.3](CONTRATO_RECTOR.md) y [refinamiento UX F5](F5_UX_CONTRATO.md). **La reconstrucción original consta de seis Changes F1–F6; F7, F8 y F9 son fases futuras añadidas por el operador, expresamente deshabilitadas.** Este archivo e Issues no autorizan trabajo, deploy ni consumo de agentes.

| Orden | Issue | Change | Resultado | Ejecutor/autoridad |
| --- | --- | --- | --- | --- |
| 1 | [#169](https://github.com/silverberdi/mini-me/issues/169) | `gacela-01-depuracion-inicial` | Retiro de emulación OpenSpec/legacy | Histórico cerrado |
| 2 | [#170](https://github.com/silverberdi/mini-me/issues/170) | `gacela-02-proyectos` | Proyectos/perfiles/contextos/proveedores | Histórico cerrado |
| 3 | [#171](https://github.com/silverberdi/mini-me/issues/171) | `gacela-03-openspec-y-revision` | OpenSpec real y revisión independiente, PR1+PR2 | Histórico cerrado |
| 4 | [#172](https://github.com/silverberdi/mini-me/issues/172) | `gacela-04-skills-base` | Skills base reutilizables | Histórico cerrado |
| 5 | [#173](https://github.com/silverberdi/mini-me/issues/173) | `gacela-05-ui-self-hosted` **reservado, no creado** | Cinco vistas MVP Tailwind/JS nativo, dos entradas primarias, observabilidad/controles F7 visuales, primera autoejecución real | **mini me**, pendiente de gates |
| 6 | [#174](https://github.com/silverberdi/mini-me/issues/174) | `gacela-06-depuracion-final` reservado | Limpieza técnica final sin funciones nuevas | **mini me** después de F5 |
| 7 | [#189](https://github.com/silverberdi/mini-me/issues/189) | `request-189-f7-capacidades-funcionales-posteriores-a` | Gestión de Requests, pausa diferida, proyecto ejecutor único, métricas y edición segura faltantes | Histórico cerrado |
| 8 | [#190](https://github.com/silverberdi/mini-me/issues/190) | **NO creado/NO autorizado** | Angular + TypeScript + Tailwind, migración de frontend sin modificar backend | **disabled**, F8 futuro |
| 9 | [#204](https://github.com/silverberdi/mini-me/issues/204) | **NO creado/NO autorizado** | OpenCode como adaptador CLI universal para modelos API externos (OpenRouter, DeepSeek, Minimax, Claude, etc.) | **disabled**, F9 futuro |

## Alcance acordado de F5

**Cinco vistas separadas, dos accesos principales:**
- Dashboard (principal): proyecto/trabajo actual, medidores tipo velocímetro para progreso y cuota verificable por modelo; gráfica de líneas de efectividad separada en calidad/autonomía, tiempo y consumo IA; atención humana y salud compactas.
- Trabajo (desde Dashboard): último terminado → en ejecución → siguiente.
- Trabajo actual (desde Dashboard/Trabajo): progreso real por stages/tareas, modelos y resultados observados; gates `HUMAN_REQUIRED` contextualizados, persistentes y accionables solo si existe autoridad.
- Proyectos (principal): lista+detalle, configuración/roles, contexto documental, control visual para solicitar pausa **diferida**.
- Backlog (desde Proyectos): Pendientes/Terminados, FIFO remoto, detalle y **formulario visual de nuevo Request** con título, descripción y aceptación obligatorios en lenguaje natural; editar, desactivar, reactivar y eliminar **lógicamente** bajo matriz de estados, pero **no funcionales en F5** si no existen los endpoints/autoridad.

F5 es **solo reconstrucción de UI + primera autoejecución real**. Reutiliza capacidades backend existentes y muestra controles nuevos deshabilitados y explicados; no simula operaciones ni añade lógica F7. Tailwind local, JS modular y FastAPI/PWA. Sin Angular hasta F8. Fuente de tickets intercambiable: GitHub actual no define el dominio del formulario. Consultar la [matriz completa de UX, seguridad y responsabilidades](F5_UX_CONTRATO.md).

## F7 — Capacidades diferidas (Issue #189, disabled)

- **Un solo proyecto ejecutor a la vez**; cambiar de proyecto solo **después** de terminar el Change iniciado, sin interrumpir ejecución ni pérdida de progreso.
- **Pausa global** desde Dashboard y **pausa por proyecto** desde Proyectos: diferidas hasta terminar Change/PR2/cierre, inmediatas si no hay trabajo; reanudación gobernada.
- **Crear/editar/desactivar/reactivar/eliminar lógicamente** Requests mediante el proveedor remoto configurado, preservando trazabilidad y sin eliminación física. **Solo no iniciados** se editan/desactivan/eliminan; un admitido usa exclusivamente `HUMAN_REQUIRED` para aclaraciones y uno finalizado es inmutable. `disabled` excluye admisión; baja lógica se conserva auditable.
- **Descripción y criterios de aceptación requeridos** en lenguaje natural; la normalización **F4 preexistente** transforma a Gherkin antes de Explore y conserva cuerpo original. NO replicar normalizador.
- Conectar instrumentación de cuotas/efectividad/tiempo/costo y edición versionada del contexto donde no haya API apta. Sin métricas inventadas, nuevo scheduler ni nueva cola.

## F8 — Angular (Issue #190, disabled)

Migrar exclusivamente la UI a Angular + TypeScript + Tailwind, conservando rutas, cinco vistas, controles, permisos, autenticación, contratos FastAPI/PWA y E2E. No duplicar backend, orquestador ni backlog. Retirar JS antiguo solo tras paridad demostrada.

## F9 — OpenCode CLI comodín para modelos API externos (Issue #204, disabled)

- Integrar **OpenCode** como un adaptador CLI ejecutable universal (comodín) en el host, dotando a modelos externos conectados por API (**OpenRouter / OR**, DeepSeek Directo, Minimax, Claude, etc.) de capacidad de ejecución interactiva en el worktree del proyecto.
- Ejecución de herramientas locales (lectura/edición de archivos, ejecución de bash/linters/tests) y compatibilidad con los workflows oficiales de OpenSpec (`propose`, `explore`, `apply`, `verify`).
- Cualquier modelo API puede operar legítimamente como implementer (`execution`) o reviewer (`independent_review`) dentro del marco de proyectos F2 sin construir runners paralelos dentro del núcleo de mini me.
- Etiquetada como **disabled; no existe Change F9 autorizado**.

## Reglas de admisión y cierre

1. Un Change OpenSpec por fase **autorizada**, no micro-Changes. F7 completada y cerrada; F8 y F9 permanecen disabled hasta autorización expresa.
2. Fuente de tickets remota, FIFO por proyecto y sin base local de backlog; Gherkin normalizado por capacidad F4. No confundir bandera de proyecto F2 `ACTIVE` con proyecto seleccionado para ejecutar F7.
3. Revisión/merge/PR1+PR2, recuperación y autorizaciones según contrato vigente; la pausa posterior F7 debe incluir cierre documental y remoto antes de detener nuevas admisiones.
4. F5 y F6 deben ejecutarse por mini me. Bootstrap PR #188 **no** equivale a F5 iniciado/ejecutado, no autoriza merge/deploy/consumo.
5. POO, SOLID, DRY, KISS, YAGNI; pruebas reales y seguridad backend.
6. No iniciar por redactar contexto. No activar scheduler productivo automáticamente.

## Historial preservado

Los 001–022, MM-R01–R10 y N01–N05 son evidencia técnica, no cartera de ejecución paralela. Históricamente se cerraron PR #140/#152 sin merge y los Issues #15, #57, #133–#138 y #162; sus resultados y decisiones no se borran. El Issue [#162](https://github.com/silverberdi/mini-me/issues/162) es antecedente visual, **no prevalece** frente al refinamiento expreso de F5 del 2026-10-26. Las menciones originales a «seis Issues únicos» y «PR #175 único abierto» describían el instante de adopción v1.2, no el estado actual de GitHub.

[Roadmap](ROADMAP.md) · [Reconciliación del legado](RECONCILIACION_LEGADO.md).
