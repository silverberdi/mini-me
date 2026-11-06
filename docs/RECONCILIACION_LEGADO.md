# Reconciliación del legado documental y de entrega

**Autoridad vigente:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md) v2.0. Este documento registra cómo leer los planes anteriores; no autoriza cambios ni declara que código o datos heredados hayan sido retirados.

## Cambio de autoridad

Los contratos v1.2/v1.3 definieron primero seis entregas F1–F6 y después añadieron F7/F8. Ese programa se conserva como historia de entrega. El contrato v2.0 sustituyó la numeración de fases por cambios discretos: un Issue corresponde a un Change OpenSpec cohesivo, autorizado por el operador. Las etiquetas F1–F10 e Issues asociados no son una secuencia de trabajo pendiente.

La migración Angular asociada históricamente a F8 está archivada y el frontend Angular forma parte del código de `main`. Las reglas de UI vigentes se interpretan desde la sección 8 del contrato rector y las decisiones de UI posteriores que sigan siendo compatibles. No tratar las referencias antiguas a F7/F8 “disabled” como estado actual.

## Reglas actuales que sustituyen decisiones históricas

| Tema | Autoridad vigente |
| --- | --- |
| Admisión y prioridad | Issue remoto más antiguo elegible dentro de un flujo autorizado; un Change activo por proyecto; sin scoring ni cola duplicada. |
| OpenSpec | El agente ejecuta workflows nativos; mini me coordina, protege el workspace y verifica evidencia observable. |
| Revisión independiente | Solo para complejidad alta, tanto de propuesta como de código; read-only, independiente del autor y ligada al SHA revisado. |
| Git, PR y cierre | Aplicar la política de merge del contrato; sync/archive nativos en rama documental nueva; cerrar el Issue tras el cierre documental confirmado. |
| Persistencia | PostgreSQL conserva configuración y estado mínimo necesario de continuidad, idempotencia, decisiones y gasto; no replica la autoridad externa. |
| Despliegue | CI/CD del proyecto; no es responsabilidad de mini me. |
| Documentación histórica | Dossiers, evidencia, specs y Changes archivados conservan su verdad histórica, pero no prevalecen sobre el contrato v2.0. |

## Referencias históricas

- F1–F6 (#169–#174) documentan el programa original de reconstrucción.
- F7 (#189) y F8 (#190) documentan capacidades posteriores; el Change F8 migró la UI a Angular.
- F9 (#204) y F10 (#207) también son etiquetas de entregas históricas.
- MM-R01–R10, N01–N05, Issues cerrados y PRs cerrados siguen disponibles como historia y evidencia, no como autorización para reabrir su alcance.

Consultar GitHub antes de citar estado actual de un Issue/PR. Las copias narrativas del estado remoto pueden quedar obsoletas.

## Reconciliación de documentos vivos

Los documentos vivos de producto, roadmap, entrega, DoR/DoD, estado, agentes y política de proveedores deben reflejar v2.0. Cuando un dossier o evidencia histórica mencione una versión anterior, conservar su contenido factual y marcar su carácter histórico; no reescribir los hechos como si hubieran sucedido bajo v2.0.

El código y PostgreSQL requieren auditoría propia. La autoridad documental no demuestra por sí sola que rutas, tablas, datos, migraciones o procesos operativos estén conformes o retirados.
