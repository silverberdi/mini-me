# Roadmap vigente — seis fases, seis Changes

**Contrato rector:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md). La secuencia 001–022, los MM-R01–R10 y N01–N05 son **historia**, no fases adicionales.

1. **F1 [#169](https://github.com/silverberdi/mini-me/issues/169)** — limpiar emulaciones de OpenSpec, lógica y DB obsoletas; preservar núcleo útil y migrar datos de forma segura. Change: gacela-01-depuracion-inicial.
2. **F2 [#170](https://github.com/silverberdi/mini-me/issues/170)** — proyecto configurable: ticket GitHub inicial, adapter strategy extensible, Git aparte, cuatro roles/modelos, contexto, skills seleccionadas. Change: gacela-02-proyectos.
3. **F3 [#171](https://github.com/silverberdi/mini-me/issues/171)** — ciclo nativo real y revisión independiente, atención humana, merge humano, sync/archive y cierre. Change: gacela-03-openspec-y-revision.
4. **F4 [#172](https://github.com/silverberdi/mini-me/issues/172)** — skills base preexistentes o complementadas donde falten. Change: gacela-04-skills-base.
5. **F5 [#173](https://github.com/silverberdi/mini-me/issues/173)** — UI responsive española; **mini me debe ejecutar autónomamente su propio Change**. Change: gacela-05-ui-self-hosted.
6. **F6 [#174](https://github.com/silverberdi/mini-me/issues/174)** — segunda depuración de lógica/DB, también **ejecutada por mini me**. Change: gacela-06-depuracion-final.

**Reglas:** exactamente un Change por fase (una o varias specs). No crear ni iniciar Changes desde este documento. Cada fase se cierra antes de iniciar la siguiente. Cada entrega tiene pruebas reales apropiadas, PR de implementación con merge humano, y cierre OpenSpec con PR documental según la fase posible. Sin microchanges, sin ejecución adelantada de fases, sin despliegue por mini me.

La aprobación del roadmap/contexto NO inicia scheduler ni permisos de gasto y NO declara resuelta la brecha entre el código actual y el contrato.

Véase [BACKLOG.md](BACKLOG.md) para Issues y [RECONCILIACION_LEGADO.md](RECONCILIACION_LEGADO.md) para tratamiento del historial.