# Definición del producto — mini me

**Fuente rectora:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md) v2.0.

mini me es un coordinador personal de cambios de software. Recibe tickets de una fuente remota, invoca agentes configurados para ejecutar workflows nativos de OpenSpec y conserva evidencias de un resultado implementado, verificado, revisado y cerrado documentalmente.

## Usuario y resultado

Un operador técnico gestiona proyectos desde la UI web/tablet/móvil, autoriza cada cambio y atiende decisiones humanas con contexto. No actúa como mensajero de prompts.

El flujo admitido es: seleccionar el Issue elegible conforme a FIFO → explore/propose nativos → revisión independiente de propuesta solo si la complejidad es alta → apply → verify por el ejecutor y correcciones acotadas → revisión independiente de código solo si la complejidad es alta → PR con la política de autorización aplicable → rama documental nueva → sync/archive nativos → PR documental → cierre remoto del Issue.

## Configuración y límites

Los perfiles de pensamiento, ejecución, revisión independiente y respaldo son configurables por proyecto y deben tener capacidad real para el workflow asignado. PostgreSQL conserva configuración y continuidad indispensables; los tickets permanecen en su proveedor, las especificaciones en OpenSpec y el código en Git.

mini me no sustituye OpenSpec, no duplica el backlog remoto, no mantiene microservicios ni gestiona el despliegue productivo. Las decisiones de seguridad, cambio material, gasto excepcional y las autorizaciones humanas del contrato no se delegan al modelo.

## Gobierno

Un Issue corresponde a un Change OpenSpec cohesivo, autorizado por el operador. Las secuencias F1–F8 describen entregas históricas y no son un plan operativo vigente. Para el orden y las reglas actuales, consultar el contrato rector v2.0 y el Issue autorizado.
