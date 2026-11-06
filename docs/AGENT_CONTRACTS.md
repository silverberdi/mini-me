# Contratos de agentes — mini me

**Fuente de autoridad:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md) v2.0 y perfiles configurados por proyecto.

## Pensamiento

Agente compatible con los workflows oficiales OpenSpec instalados. Explora, propone, actualiza y verifica contexto conforme a su responsabilidad; ejecuta sync/archive nativos para cierre documental. Si OpenSpec no ofrece opciones para una pregunta contextual, usa ticket/artefactos/contexto y responde solo cuando tiene evidencia y autoridad. No autoriza decisiones reservadas.

## Ejecución

Agente con capacidad real de editar archivos y ejecutar comandos. Implementa y corrige mediante OpenSpec Apply, ejecuta pruebas pertinentes y realiza Verify nativo. Reanuda sobre el mismo candidato con contexto basado en evidencia; se detiene ante regresión o identidad ambigua.

## Revisión independiente

Se invoca únicamente para complejidad alta, tanto para revisar propuesta como código. El revisor debe ser distinto de los autores del candidato y operar en modo read-only. El resultado se vincula a los artefactos/SHA revisados; los hallazgos vuelven a pensamiento o ejecución para corrección. No reescribe ni certifica su propio trabajo.

## Respaldo

Proveedor, modelo y capacidad configurables. Solo se usa si puede ejecutar el workflow real requerido y si permisos y presupuesto lo autorizan. Una API de texto no sustituye una CLI que deba editar archivos.

## Responsabilidad de mini me

Selecciona los perfiles configurados, invoca skills instaladas, preserva checkpoints, presenta preguntas/opciones fieles y ejecuta operaciones deterministas autorizadas sobre Git y tickets. No crea contenido semántico OpenSpec ni programa en lugar de los agentes.

## Evidencia y límites

Registrar proveedor, modelo/workflow, repositorio, rama, SHA, resultado, pruebas y decisiones humanas relevantes. No consumir cuota no autorizada, fingir ejecución ni alterar el candidato durante revisión. Las etiquetas F5/F6 y sus requisitos de autoejecución pertenecen a la historia de entregas, no son un gate especial para cambios futuros.
