# Gestión de tickets y PR — GitHub inicial

**Autoridad:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md). GitHub Issues es la fuente remota de tickets inicial; Azure Boards podrá añadirse mediante adaptador mínimo cuando sea necesario. Integración de tickets separada de integración Git/PR.

## Fuente y selección
No replicar tickets como cola propia en PostgreSQL. Consultar Issues abiertos elegibles, ordenar por created_at ascendente y resolver empates con ID estable. Procesar un cambio activo por proyecto; no saltar bloqueos silenciosamente ni usar score o prioridad sintética.

## Contrato básico de tickets
Listar, leer, crear, comentar hallazgos/avance/opciones y cerrar solo tras sync/archive y PR documental fusionado. El ticket nuevo debe incluir objetivo, comportamiento, alcance y criterios verificables; el agente usa skill seleccionada donde corresponda, la API determinista ejecuta escritura.

## PR implementación
Rama única del candidato → push y PR → evidencia de verify/review → humano autoriza merge para SHA exacto → mini me ejecuta por integración Git respetando protecciones. Los agentes no se autoautorizan.

## PR documental
Después del merge anterior: rama nueva desde main, pensamiento con OpenSpec sync/archive nativos → commit/push/PR documental → merge automatizable SOLO con política y protecciones Git permitiéndolo → cerrar Issue → siguiente.

## Backlog de esta reconstrucción
Únicamente Issues [#169](https://github.com/silverberdi/mini-me/issues/169)–[#174](https://github.com/silverberdi/mini-me/issues/174), uno por fase/Change OpenSpec. No cerrar ni migrar automáticamente #133–#138, #162 u otros tickets anteriores por aprobar la planificación. Ver [BACKLOG.md](BACKLOG.md).