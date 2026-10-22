# Definición del producto — mini me

**Fuente rectora:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md) v1.2.

mini me es un coordinador pequeño de desarrollos de software que convierte tickets remotos en resultados mediante agentes y workflows nativos de OpenSpec. **No programa ni emula OpenSpec.**

## Usuario
Un operador técnico supervisa proyectos desde una instalación personal, en escritorio/tablet/móvil, sin pasar mensajes manualmente entre agentes.

## Resultado obligatorio
Proyecto activo → ticket abierto elegible más antiguo del proveedor remoto (GitHub inicialmente) → rama → Propose → revisión independiente de propuesta → Apply → Verify + correcciones → revisión independiente de código según política → PR → autorización humana de merge → rama fresca desde main → Sync/Archive nativos → PR documental con merge autorizado → cerrar issue → siguiente.

Preguntas de OpenSpec: opciones originales se muestran; sin opciones el agente de pensamiento consulta ticket/specs/contexto para resolver solo lo permitido, o solicita respuesta humana informada. Estado mínimo se conserva para continuar sin duplicar acciones.

## Configuración
Cuatro roles independientes: pensamiento, ejecución, revisión y respaldo; proveedor/modelo/CLI compatibles configurables por proyecto; esfuerzo medio por defecto para razonamiento/ejecución/revisión y menor compatible para sync/archive. Skills preexistentes y AGENTS.md apuntan al contexto canónico. Origen de tickets extensible sin implementar ADO aún.

## No objetivos
Implementar OpenSpec en Python, generar plantillas de specs, emular sync/archive, motor propio de riesgo, scheduler con scoring, backlog DB duplicado, proveedores hardcodeados, plataforma universal de plugins, microservicios, despliegue productivo o ejecución sin autorización de merge humano.

## Reconstrucción
Exactamente 6 Changes F1–F6 (issues #169–#174). F5 y F6 desarrolladas POR mini me. F3 debe demostrar un recorrido real completo. POO, SOLID, DRY, KISS, YAGNI; reducir código y DB, no ampliar complejidad.

**No declarar valor por cantidad de tests o líneas; sí por E2E real y autonomía demostrada.**