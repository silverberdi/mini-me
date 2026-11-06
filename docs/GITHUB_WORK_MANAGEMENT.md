# Gestión de tickets y PR

**Autoridad:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md) v2.0. GitHub Issues es la fuente inicial de tickets; la integración de tickets y la de Git/PR son responsabilidades separadas.

## Fuente y selección

Consultar Issues abiertos elegibles en la fuente remota y ordenar por fecha de creación ascendente, con desempate estable por ID. La admisión FIFO opera únicamente dentro de un flujo autorizado por el operador. Mantener un Change activo por proyecto; no saltar bloqueos silenciosamente ni duplicar la cola en PostgreSQL.

## Contrato de tickets

El adaptador remoto lista, lee, crea, comenta y cierra Issues conforme a la política. El Issue contiene objetivo y criterios verificables. Cerrar solo después de confirmar el cierre documental y su PR fusionado.

## PR de implementación

Publicar el candidato con SHA identificable y evidencia de Verify/pruebas. Aplicar la política de complejidad del contrato: baja/moderada puede fusionarse automáticamente; alta requiere el acuse humano informativo previo. No autoautorizar excepciones de seguridad, gasto o alcance.

## PR documental

Después de confirmar el merge de implementación, crear rama nueva desde `main` actualizado; ejecutar Sync/Archive mediante workflows nativos; abrir PR documental y fusionarlo bajo la política del contrato antes de cerrar el Issue.

## Historia del backlog

Los Issues #169–#174 (#F1–F6), #189/#190 (#F7/F8) y posteriores números de fase son referencias históricas de entregas, no una lista activa ni una secuencia obligatoria. Los Issues heredados y PR cerrados conservan su historial. Para conocer el backlog y estado actuales, consultar GitHub; este documento no mantiene una copia de la cartera.
