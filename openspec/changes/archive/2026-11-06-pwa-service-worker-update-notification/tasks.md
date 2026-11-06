## 1. Aviso y activación de actualizaciones

- [x] 1.1 Escuchar actualizaciones del Angular Service Worker y mostrar un aviso accesible en español solo cuando la nueva versión del shell esté lista.
- [x] 1.2 Conectar «Recargar» con la activación de la versión lista y recargar después de activarla; no recargar automáticamente ni mostrar avisos cuando SwUpdate esté deshabilitado o no haya versión lista.

## 2. Verificación

- [x] 2.1 Añadir pruebas frontend focalizadas para el aviso en `VERSION_READY`, ausencia de aviso sin actualización lista y activación/recarga solo al pulsar «Recargar».
- [x] 2.2 Ejecutar `npm --prefix frontend test` y `npm --prefix frontend run build`; ambos deben terminar con código 0.
- [x] 2.3 Verificar en un navegador, servido por HTTP local y con el service worker Angular real, que una segunda versión del shell provoca el aviso y que «Recargar» carga esa versión; registrar la evidencia del resultado y del SHA candidato sin usar despliegue productivo. Evidencia: en Chrome sobre `http://127.0.0.1:4175/dashboard`, el shell `e2e-v1` mostró el aviso y el botón «Recargar»; al pulsarlo, la página cargó `e2e-v2`. SHA base del candidato: `3cbc0056f8c1f6796f00256a21da5a6a263ebb87` (cambios locales sin commit).
