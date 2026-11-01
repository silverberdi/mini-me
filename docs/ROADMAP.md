# Roadmap de Arquitectura y Evolución de mini me

**Contexto:** Este documento es un resumen informativo y de contexto arquitectónico de alto nivel.
**Autoridad operativa:** Conforme al [Contrato Rector v1.3](CONTRATO_RECTOR.md), la **única fuente de verdad autoritativa para el trabajo, admisión y secuencia de ejecución es el repositorio remoto (GitHub Issues)** en orden ascendente FIFO. La admisión de trabajo no se bloquea por falta de pre-inscripción en este archivo.

| Fase | Issue | Identidad OpenSpec | Objetivo | Estado |
| --- | --- | --- | --- | --- |
| **F1** | [#169](https://github.com/silverberdi/mini-me/issues/169) | `gacela-01-depuracion-inicial` | Retiro seguro de emulaciones y código/DB obsoletos | Cerrada |
| **F2** | [#170](https://github.com/silverberdi/mini-me/issues/170) | `gacela-02-proyectos` | Proyectos, contextos, proveedores de tickets y Git/PR separados | Cerrada |
| **F3** | [#171](https://github.com/silverberdi/mini-me/issues/171) | `gacela-03-openspec-y-revision` | Ciclo OpenSpec nativo con E2E, atención humana y cierre de dos PRs | Cerrada |
| **F4** | [#172](https://github.com/silverberdi/mini-me/issues/172) | `gacela-04-skills-base` | Skills y bootstrap complementarios | Cerrada |
| **F5** | [#173](https://github.com/silverberdi/mini-me/issues/173) | `gacela-05-ui-self-hosted` | Reconstrucción visual de 5 vistas y autoejecución | Cerrada |
| **F6** | [#174](https://github.com/silverberdi/mini-me/issues/174) | `gacela-06-depuracion-final` | Depuración final ejecutada por mini me | Cerrada |
| **F7** | [#189](https://github.com/silverberdi/mini-me/issues/189) | `request-189-f7-capacidades-funcionales...` | Pausa diferida, único proyecto ejecutor, gestión de Requests | Cerrada |
| **F8** | [#190](https://github.com/silverberdi/mini-me/issues/190) | `req-190-f8-migracion-frontend-angular-tailwind` | Migración de la UI a Angular + TypeScript + Tailwind | Implementada y en producción |
| **F9** | [#204](https://github.com/silverberdi/mini-me/issues/204) | `req-204-f9-opencode-cli...` | OpenCode CLI como adaptador universal para modelos API | Cerrada |
| **F10**| [#207](https://github.com/silverberdi/mini-me/issues/207) | `req-207-f10-desacoplamiento-asincrono...` | Desacoplamiento asíncrono y telemetría de cuotas | Cerrada |
| **F11+**| Backlog GitHub | Según Issue remoto | F11 Web Push (#208), F12 Limpieza (#211), F13 Modelos (#212), etc. | En curso vía GitHub FIFO |

**Principios de Alcance:**
- La secuencia y prioridades de desarrollo se definen y gestionan directamente en GitHub Issues.
- Las fases posteriores construyen sobre la base tecnológica actual (FastAPI en backend, Angular en frontend).
- Cada Change OpenSpec debe enfocarse estrictamente en la necesidad descrita en el Issue admitido sin burocracia de doble registro documental.
