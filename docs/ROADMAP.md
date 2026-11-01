# Roadmap vigente — F1–F6 reconstrucción original; F7–F10 evolución posterior

**Autoridad:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md) v1.3; diseño operativo concreto de F5 en [F5_UX_CONTRATO.md](F5_UX_CONTRATO.md). 001–022, MM-R01–R10 y N01–N05 son **historia**, no fases alternativas.

| Fase | Issue | Identidad OpenSpec | Objetivo | Situación planificada |
| --- | --- | --- | --- | --- |
| **F1** | [#169](https://github.com/silverberdi/mini-me/issues/169) | `gacela-01-depuracion-inicial` | Retiro seguro de emulaciones y código/DB obsoletos | Fase histórica cerrada |
| **F2** | [#170](https://github.com/silverberdi/mini-me/issues/170) | `gacela-02-proyectos` | Proyectos, contextos, proveedores de tickets y Git/PR separados, agentes configurables | Fase histórica cerrada |
| **F3** | [#171](https://github.com/silverberdi/mini-me/issues/171) | `gacela-03-openspec-y-revision` | Ciclo OpenSpec nativo con E2E, atención humana y cierre de dos PRs | Fase histórica cerrada |
| **F4** | [#172](https://github.com/silverberdi/mini-me/issues/172) | `gacela-04-skills-base` | Skills y bootstrap complementarios | Fase histórica cerrada |
| **F5** | [#173](https://github.com/silverberdi/mini-me/issues/173) | `gacela-05-ui-self-hosted` (reservado) | **UI MVP** HTML/JS nativo/Tailwind; 5 vistas, 2 accesos primarios, E2E y primera ejecución autónoma de mini me | Siguiente, aún no iniciada |
| **F6** | [#174](https://github.com/silverberdi/mini-me/issues/174) | `gacela-06-depuracion-final` (reservado) | Depuración final después de F5, ejecutada por mini me, sin nuevas funcionalidades | Después del cierre F5 |
| **F7** | [#189](https://github.com/silverberdi/mini-me/issues/189) | `request-189-f7-capacidades-funcionales-posteriores-a` | Conectar funciones faltantes: pausa diferida, único proyecto ejecutor, gestión de Requests, normalización F4 y métricas/contexto faltantes | Fase completada y cerrada |
| **F8** | [#190](https://github.com/silverberdi/mini-me/issues/190) | **sin Change creado** | Migrar exclusivamente la capa frontend a **Angular + TypeScript + Tailwind** | **disabled**, solo planificación |
| **F9** | [#204](https://github.com/silverberdi/mini-me/issues/204) | **sin Change creado** | OpenCode como adaptador CLI universal para modelos API externos (OpenRouter, DeepSeek, Minimax, Claude, etc.) | **disabled**, solo planificación |
| **F10** | [#207](https://github.com/silverberdi/mini-me/issues/207) | **sin Change creado** | Desacoplamiento asíncrono, telemetría real de cuotas 5h, reactividad y pulimento PWA, auto-recuperación de Runs | **autorizada**, posterior a F9 |

**Reglas invariables:**
- Las seis fases de reconstrucción **originales F1–F6** no se reescriben, fragmentan ni alteran; F7/F8/F9 son extensión posterior decidida expresamente. Una fase autorizada usa un único Change OpenSpec con las specs que necesite, sin micro-Changes.
- Las Issues F8/F9 llevan `disabled` y dependencia formal; F10 queda autorizada para crear un único Change después del cierre gobernado de F9. La autorización documental no autoriza Apply, scheduler, PR/merge ni despliegue.
- F5 puede funcionar sobre CLI/API actuales hasta que su propia UI esté construida; **debe autoejecutarse materialmente por mini me**. F6 también. PR [#188](https://github.com/silverberdi/mini-me/pull/188) es bootstrap excepcional separado y Draft hasta superar sus gates.
- Frontend F5: Tailwind y JS nativo; las futuras funciones de F7 deben tener controles visuales honestamente deshabilitados en F5. Angular se reserva expresamente para F8.
- Fuente autoritativa de tickets: proveedor configurable (GitHub actual, reemplazable). No hay backlog PostgreSQL duplicado. Gherkin es normalización F4, no requisito de entrada del humano.
- Secuencia gobernada, E2E real, no gasto/despliegues no autorizados; ningún Change F8/F9 arranca automáticamente tras cerrar F7.

Véanse [BACKLOG.md](BACKLOG.md), [F5_UX_CONTRATO.md](F5_UX_CONTRATO.md), [RECONCILIACION_LEGADO.md](RECONCILIACION_LEGADO.md) y [CHANGE_DELIVERY_CONTRACT.md](CHANGE_DELIVERY_CONTRACT.md).
