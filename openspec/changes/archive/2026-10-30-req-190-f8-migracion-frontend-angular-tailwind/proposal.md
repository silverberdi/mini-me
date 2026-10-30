# Proposal

## Why

F5 y F7 establecen una interfaz web funcional en HTML, JavaScript modular y Tailwind, pero dejan registrada una migración futura del frontend a Angular + TypeScript + Tailwind. Este Change documenta ese alcance posterior para conservar la paridad visual, funcional, de seguridad y de accesibilidad sin alterar FastAPI ni adelantar la fase F8 mientras la Issue #190 siga planificada y `disabled`.

## What Changes

- Registrar una migración futura exclusivamente de la capa frontend: componentes, rutas, formularios, estado y un cliente HTTP tipado en Angular + TypeScript + Tailwind.
- Preservar las cinco vistas independientes, los dos destinos principales de navegación, la autenticación validada por backend, la accesibilidad, el comportamiento responsive y las capacidades visuales y gobernadas entregadas por F5/F7.
- Mantener FastAPI, los contratos de API, los modelos durables, las reglas de negocio, OpenSpec, el proveedor de tickets, el control plane y los permisos como autoridades sin reescribirlos ni duplicarlos.
- Exigir evaluación de bundle, rendimiento, memoria, responsive, PWA/offline seguro y pruebas unitarias y E2E reales de navegador; retirar el frontend JavaScript legacy únicamente después de demostrar paridad y ausencia de listeners o pollers duplicados.
- Mantener seguridad XSS/CSP/contenido seguro, no exponer secretos, no cachear respuestas autenticadas y conservar la validación de autenticación/autorización en el servidor.
- Mantener F8 posterior a F7 y deshabilitada: este Change no inicia ingeniería Angular, no habilita la Issue, no crea PR, no despliega, no ejecuta scheduler ni consume agentes o gasto.

## Capabilities

### New Capabilities

Ninguna. La migración futura debe conservar y extender los contratos de frontend ya existentes, no crear una autoridad paralela.

### Modified Capabilities

- `pwa-app-shell-and-queue`: conservar las cinco rutas, los dos destinos principales, el contexto autorizado, el ciclo único de refresco y la ausencia de mutaciones durante polling al cambiar la implementación del frontend.
- `pwa-responsive-and-offline-pwa`: conservar responsive, accesibilidad, temas y PWA/offline seguro; el service worker solo podrá cachear el shell público y nunca respuestas operativas autenticadas.
- `f5-self-hosted-delivery`: ampliar la aceptación futura para exigir paridad verificable entre Angular y el frontend legacy, pruebas reales de navegador y retiro seguro del legacy sin duplicación de listeners o pollers.

## Impact

El impacto futuro queda limitado al cliente web y a su toolchain Angular/TypeScript/Tailwind, junto con pruebas unitarias y E2E de navegador y la configuración de bundle/PWA necesaria para evaluarlo. No se modifican la API FastAPI, contratos remotos, PostgreSQL, autenticación/autorización, control plane, proveedor de tickets, workflows nativos de OpenSpec ni el despliegue CI/CD. La implementación y la retirada del legacy requieren una autorización posterior de F8, evidencia contra un SHA inmutable y paridad aprobada antes de eliminar la interfaz existente.
