# F4 — preflight del runtime de servicio

Fecha: 2026-10-24

## Resultado

`WAITING_SERVICE_RUNTIME`

La sesión de ejecución está en macOS (`Darwin`, usuario del operador). No se observó un servidor Ubuntu ni un runtime de aplicación ejecutándose bajo la identidad `minime`. Tampoco existe un usuario local `minime` o `silverman`, un alias SSH configurado o una conexión de servicio que permita verificar el entorno remoto.

Se observaron únicamente contenedores PostgreSQL locales desechables; no se utilizaron para sustituir el PostgreSQL del servicio ni se hicieron migraciones o escrituras.

## Controles no atribuibles al servidor

- GitHub App: no verificable bajo la identidad de instalación del servicio. No se usó `gh` ni una sesión personal como sustituto.
- PostgreSQL/runtime/worktree del servicio: no verificables desde este checkout.
- Perfiles Codex/Antigravity y sus credenciales de servicio: no verificables bajo `minime`.
- Cuota y presupuesto: no existe un techo monetario F4 observable o autorizado en esta sesión.
- Efectos remotos e Issue controlado: no se seleccionaron ni modificaron recursos externos.

## Observaciones locales sin inferencia

- Codex CLI `0.161.0` está instalado, pero la sesión observada es interactiva del operador.
- AGY `1.4.7` está instalado y `agy models` mostró `gemini-3.8-flash-medium`.
- El scheduler configurado está `DISABLED`; OpenRouter/fallback permanecen desactivados.
- Invocaciones pagadas F4 realizadas: `0`.

## Continuación requerida

Proporcionar al runtime autorizado una ruta de acceso de solo lectura/preflight bajo `minime` (endpoint o canal oficial), identidad GitHub App verificable, PostgreSQL desechable/worktree administrado y techo monetario explícito. Después puede ejecutarse un único recorrido Greenfield sin reintentos ni fallback, registrando consumo y operaciones GitHub antes de preparar PR1.
