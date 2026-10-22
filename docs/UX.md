# Contrato UX — mini me, la gacela

**Autoridad:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md). UI en español desde los primeros wireframes, densa pero clara, con jerarquía, distribución eficiente y sin espacios desperdiciados.

## Móvil — observación
Mostrar qué hace ahora, qué acaba de hacer, qué viene, si hay bloqueos y qué necesita el humano. Atender opciones/preguntas simples y aprobar acciones cuando sea adecuado; no replicar la consola completa.

## Tablet — operación
Vista master-detail y drawers/split views para operar proyectos, tickets y decisiones. Aprovechar espacio sin saturación.

## Web — control center
Paneles redimensionables/colapsables, disposición persistente útil, modales/drawers para operaciones. Proyectos, agentes/modelos, cambio activo, propuesta/apply/verify/revisión, PR, cierre documental, notificaciones y errores.

## Bandeja de intervención humana
- Capturar y distinguir mensaje/opciones ORIGINALES del workflow OpenSpec y alternativas/recomendación producidas por pensamiento.
- Si no hay opciones y el agente no puede resolver con información+autoridad, pregunta clara al operador con contexto mínimo y texto libre cuando corresponda.
- Mostrar qué necesita, por qué, alternativas, consecuencias y qué sucede tras responder.
- Reanudar el mismo cambio/branch/checkpoint después de respuesta; nunca transferir manualmente prompts entre agentes.
- Notificación especial de **merge humano** que presenta PR/SHA, alcance, evidencias y confirmación explícita.

## Errores
Siempre: qué falló, qué trabajo se conservó, si se reintentará (y cuándo), si hace falta intervención. No depender solo de colores.

No poner al usuario frente a IDs internos, logs y estados accidentales como reemplazo de información útil. UI F5 debe ser diseñada y desarrollada por mini me sobre su propio repositorio.

## Criterios UX históricos que deben conciliarse en F5
El [Issue #162](https://github.com/silverberdi/mini-me/issues/162), ahora cerrado como ticket independiente, contiene requisitos previamente aprobados de **cinco vistas independientes**: Dashboard, Trabajo, Trabajo actual, Proyectos y Backlog; navegación, métricas, atención humana y edición segura de documentos. Su contenido NO se descarta ni genera un séptimo Change: la Fase 5 [#173](https://github.com/silverberdi/mini-me/issues/173) debe leerlo y reconciliarlo con el contrato rector, incluido el conflicto explícito sobre equivalencia funcional móvil frente a observabilidad prioritaria. Si es material, solicitar decisión humana en Propose; no elegir en silencio ni reconstruir una UI obsoleta por inercia.
