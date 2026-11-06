# Estado operativo — mini me

**Autoridad:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md) v2.0. Este documento resume los estados visibles; no define una máquina paralela ni sustituye el modelo implementado.

El ciclo visible es: Issue seleccionado en una admisión autorizada → Explore/Propose → Apply → Verify/correcciones → revisión independiente solo para complejidad alta → PR y autorización aplicable → Sync/Archive nativos → PR documental → cierre remoto.

Preguntas humanas preservan la pregunta vigente, contexto y opciones disponibles; una respuesta autorizada reanuda el mismo trabajo. Fallos y esperas preservan los artefactos y el checkpoint necesario. Antes de repetir una operación externa, mini me observa su estado para evitar efectos duplicados.

Las representaciones de UI deben distinguir progreso, bloqueo, espera, fallo, estado terminal y estado desconocido a partir de evidencia real. No inferir trabajo en curso ni cerrar un Run solo porque la interfaz o el Issue haya cambiado.

La implementación puede mantener estados internos de recuperación que el contrato permita y el caso real justifique. Su necesidad, atomicidad y consumidores se evalúan en cambios autorizados; este resumen no autoriza eliminarlos ni agregarlos.
