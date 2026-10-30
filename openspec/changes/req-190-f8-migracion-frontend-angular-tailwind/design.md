# Design

## Context

Este Change registra una migración futura de la capa web descrita en `proposal.md`; no autoriza su ejecución mientras F8 permanezca planificada y `disabled`. F5/F7 proporcionan el comportamiento observable que debe conservarse: cinco vistas independientes, navegación primaria limitada a Dashboard y Proyectos, contexto autorizado, refresco único, métricas honestas, controles F7 no disponibles sin autoridad y shell PWA sin respuestas autenticadas en caché.

Las autoridades permanecen separadas: FastAPI y sus contratos son la única API; el backend valida autenticación, autorización, permisos, estados obsoletos y mutaciones. OpenSpec, el proveedor de tickets, el control plane, los modelos durables y CI/CD tampoco se trasladan al cliente. El frontend actual JavaScript y sus listeners/pollers son el sistema de referencia hasta que una candidata Angular alcance paridad demostrada.

## Goals / Non-Goals

**Goals:**

- Sustituir únicamente la capa de presentación por una aplicación Angular + TypeScript + Tailwind, manteniendo las rutas, contratos HTTP, cinco vistas, dos destinos primarios, autenticación, accesibilidad, responsive, gráficos, medidores y estados de datos ya especificados.
- Encapsular las llamadas al backend en un cliente HTTP tipado y mantener en el cliente solo estado de navegación, selección, refresco y presentación; las decisiones y cálculos autoritativos continúan en FastAPI.
- Conservar un único ciclo de bootstrap/refresco y un único propietario de listeners, timers, suscripciones y pollers, con cancelación al cambiar de vista o destruir componentes.
- Validar la candidata Angular contra la interfaz legacy en navegador real para escritorio, tablet y móvil, incluyendo bundle, rendimiento, memoria, accesibilidad, responsive, PWA/offline seguro, seguridad y E2E antes de retirar el legacy.
- Permitir rollback manteniendo la entrega legacy hasta completar la comparación, y retirar sus rutas, listeners, pollers, configuración y pruebas exclusivas solo cuando la paridad esté aprobada.

**Non-Goals:**

- No modificar FastAPI, contratos de API, PostgreSQL, modelos, reglas de negocio, control plane, permisos, autenticación de servidor, proveedor de tickets, OpenSpec ni el despliegue CI/CD.
- No crear una segunda API, un motor de ejecución, un backlog, una fuente de verdad, una autoridad de permisos ni mediciones client-side que sustituyan observaciones verificadas del backend.
- No implementar capacidades F7 ausentes; los controles sin autoridad permanecen visibles, accesibles y deshabilitados con su explicación.
- No comenzar instalación, migración, PR, scheduler, despliegue, consumo de agentes/gasto o retiro del frontend legacy durante este Change de planificación.

## Decisions

### Aplicación Angular como sustituto de la vista, no del dominio

La aplicación se organizará por rutas/vistas, componentes presentacionales, servicios de navegación/refresco y un cliente HTTP tipado que refleje los contratos FastAPI existentes. La autenticación se transportará mediante los mecanismos ya aprobados por el backend; ningún secreto se compilará ni almacenará en el bundle. Las respuestas autenticadas permanecerán en memoria y no serán persistidas por el service worker.

Se elige esta separación sobre mover reglas al cliente porque preserva la autoridad del servidor, facilita pruebas de contrato y reduce el acoplamiento entre Angular y el control plane. No se introducirá un store global o una capa de dominio adicional salvo que el inventario de F8 demuestre una necesidad concreta de evitar estado duplicado.

### Rutas y navegación compatibles

El router Angular conservará URL y contexto autorizado para Dashboard, Trabajo, Trabajo actual, Proyectos y Backlog. Dashboard y Proyectos serán los únicos destinos primarios; los demás se alcanzarán mediante enlaces contextuales. Los parámetros de proyecto, Request, Run o etapa se validarán y recargarán desde la autoridad backend; un identificador ausente o prohibido producirá un error explícito y nunca una selección silenciosa.

Se elige preservar rutas observables sobre una reconstrucción de navegación porque permite comparar deep links, back/forward y refresh entre ambas implementaciones y evita que la migración rompa enlaces operativos.

### Refresco y ciclo de vida único

Un servicio de refresco compartido será el único propietario del intervalo seleccionado, la lectura inmediata y la recuperación tras reconexión. Los componentes se suscribirán de forma acotada y liberarán sus suscripciones al destruirse; cambiar de vista no creará otro timer ni otro poller. Las operaciones de lectura podrán cancelarse al cambiar el contexto, pero ninguna respuesta del cliente podrá convertir una lectura en mutación.

Se elige una única coordinación explícita sobre timers por componente porque los escenarios exigen ausencia verificable de listeners/pollers duplicados y porque conserva el ciclo de F5 durante la migración.

### Tailwind y responsive sin alterar semántica accesible

Tailwind se usará como capa de presentación local, con estilos y breakpoints para control-center web, master/detail tablet y navegación enfocada móvil. Los componentes conservarán HTML semántico, foco visible, nombres accesibles, alternativas textuales para gráficas, contraste, touch targets y reflow hasta 400% de zoom. Los estados disabled, offline, stale, error y No disponible mostrarán su motivo en texto accesible.

Se elige reutilizar las capacidades de Tailwind del frontend existente y los patrones visuales verificados sobre introducir una biblioteca de componentes que pueda duplicar estilos, bundle y semántica.

### PWA y límites de caché

El shell público, manifest e iconos se servirán mediante el mecanismo PWA de Angular elegido para el proyecto. El service worker solo podrá cachear recursos estáticos versionados. Nunca cacheará respuestas de API, credenciales, decisiones, cuerpos de Requests ni documentos autenticados; offline bloqueará mutaciones y no encolará replay. Al reconectar, una lectura autoritativa precederá cualquier acción permitida y logout limpiará el estado autenticado en memoria.

Se elige una política de shell-only sobre estrategias offline de datos porque evita convertir el navegador en una segunda persistencia operativa y respeta la prohibición de replay de mutaciones.

### Evidencia de paridad y retiro seguro

F8 deberá capturar una matriz requisito→escenario→prueba→evidencia contra un SHA inmutable, con comandos, códigos de salida, capturas y efectos observables de navegador real. La comparación incluirá bundle, rendimiento, memoria, responsive, accesibilidad, seguridad, PWA/offline y unit/E2E. Las pruebas mock solo podrán cubrir unidades/contratos y no acreditarán integración real.

El frontend legacy se conserva durante el periodo de comparación. El Removal Ledger de F8 deberá identificar sus entrypoints, writers/consumidores, listeners, pollers, configuración, scripts y pruebas; tras E2E de paridad se migrarán los consumidores y se retirarán únicamente las rutas sustituidas. Las migraciones de datos y artefactos históricos se retendrán. Si falta cualquier dimensión de evidencia, se mantiene legacy y la candidata queda sin paridad.

## Risks / Trade-offs

- **[Riesgo]** Diferencias silenciosas en autenticación, permisos o estados obsoletos → **Mitigación:** cliente tipado sin autoridad, validación backend obligatoria y E2E real de respuestas permitidas y rechazadas.
- **[Riesgo]** Angular duplica listeners, timers o pollers durante coexistencia → **Mitigación:** propietario único del refresco, teardown verificable y pruebas que cuentan invocaciones durante navegación y cambios de intervalo.
- **[Riesgo]** Service worker expone datos autenticados o replaya mutaciones → **Mitigación:** caché limitada al shell público, inspección de cachés, logout/reconexión E2E y mutaciones bloqueadas offline.
- **[Riesgo]** Bundle, memoria o rendimiento empeoran al añadir el toolchain → **Mitigación:** mediciones comparables sobre las mismas vistas y dispositivos; no retirar legacy hasta cumplir criterios aprobados en F8.
- **[Riesgo]** Paridad visual no implica paridad funcional o accesible → **Mitigación:** matriz separada de comportamiento, accesibilidad, responsive, seguridad, datos verificables y visualización, con validación humana vigente.
- **[Riesgo]** Coexistencia prolongada crea dos interfaces activas → **Mitigación:** flag/entrega temporal con fecha y criterio de retiro documentados; retiro en el mismo Change de implementación después de paridad, o bloqueo explícito con autorización humana si existe un consumidor legítimo.

## Migration Plan

1. Con una autorización futura explícita de F8, inventariar el frontend legacy, sus consumidores, contratos, rutas, writers, listeners, pollers, cachés, scripts y pruebas; registrar el estado inicial en el Removal Ledger.
2. Implementar la shell Angular y el cliente HTTP tipado contra los contratos existentes, comenzando por autenticación, navegación y ciclo de refresco; no modificar la API ni habilitar capacidades F7.
3. Migrar las cinco vistas y sus estados de datos, controles, gráficos, medidores, errores, accesibilidad, responsive y PWA shell. Añadir pruebas unitarias y de contrato proporcionales, y E2E de navegador contra servicios autorizados reales.
4. Ejecutar la matriz de paridad en web, tablet y móvil, medir bundle/rendimiento/memoria y comprobar cachés, logout, reconexión, permisos, estados obsoletos y ausencia de duplicación. La evidencia se vincula a la candidata y SHA exactos.
5. Mantener legacy como rollback hasta revisión y aceptación de paridad. Si falla una dimensión, corregir mediante el workflow OpenSpec o revertir la entrega Angular sin alterar backend ni datos.
6. Tras aprobación, migrar consumidores de la entrada legacy, repetir E2E después del retiro y eliminar solo entrypoints/configuración/listeners/pollers/tests muertos identificados por el ledger. Conservar historial, migraciones aplicadas y evidencia.

El rollback de una candidata no requiere revertir FastAPI: se vuelve a la entrega legacy mientras sus contratos sigan vigentes. No se declara retirada ni finalización si quedan consumidores legítimos, rutas duplicadas activas o evidencia incompleta.

## Open Questions

Ninguna material para este diseño. Los detalles de versión de Angular, organización concreta de módulos y umbrales numéricos de rendimiento deberán fijarse durante el Change autorizado únicamente si no cambian los contratos, la arquitectura ni la condición de paridad.
