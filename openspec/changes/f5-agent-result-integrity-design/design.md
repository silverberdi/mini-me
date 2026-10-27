## Contexto y estado autoritativo

- Producto: mini me, instalación personal; coordinador de agentes que utiliza **OpenSpec nativo** sin emular sus workflows. Contrato rector v1.3 y `openspec/config.yaml` prevalecen sobre material histórico. F1–F4 cerradas; F5 activa; F6/F7/F8 fuera.
- Identidades intocables: Run `4eb3f3f7-41df-4483-9a97-ce59bbcc0db2`; Request `silverberdi/mini-me#173`; Change F5 `gacela-05-ui-self-hosted`; rama `request-173-f5-ui-mvp-y-primera-autoejecución-real-d`; base SHA `84f1d6a6d7e0358cc960e6e26198667b9dd7c085`.
- Estado reportado: producción `fdc97430741697ab9ca4e3485330386eea5cd1c2`, API saludable, scheduler `inactive/disabled`; Run en `EXPLORING/PAUSED`, sin propuesta F5. Este diseño no es prueba nueva de estado productivo.
- Hitos previos: PR #192 presupuesto proveedor, #193 actualización GitHub Issue, #194 parser Explore/checkpoint. **No** se consideran automáticamente correctos por estar fusionados.
- Evento observado: `CliAgentRunner` establece `output_truncated=True` cuando una línea de stdout/stderr supera `MAX_LINE_CHARS=4000` o una salida supera `MAX_OUTPUT_LINES=2500`; trunca cada línea y el total antes de entregar `stdout`. Un evento Codex NDJSON con aclaración de 4.715 caracteres supera el límite. `_run_explore` devuelve FAILED/PAUSED si `res.output_truncated`, sin distinguir origen del exceso.

## Censo de autoridad existente (ver `evidence/code-census.md`)

1. `AgentProcessConfinement.run_confined_async_subprocess` supervisa el proceso y devuelve bytes `stdout/stderr` saneados; la captura no distingue por sí sola mensaje de asistente, eventos de herramientas o errores.
2. `CliAgentRunner.run` prepara comando y confinamiento, opcionalmente `--output-schema` + `--output-last-message`, transforma bytes a líneas, recorta logs y publica `AgentExecutionResult` con `response_output`, `diagnostic_output`, flags de truncación y exit code. Esa es la **frontera única existente** para normalizar evidencias; no se añade un `AgentResponseManager` paralelo.
3. Normalizador, clasificación, preparación de PR y Verify tienen ejemplos de último mensaje estructurado; `tests/test_f4_structured_output.py` demuestra que una respuesta nativa de >4.000 caracteres puede ser válida aunque el diagnóstico esté truncado.
4. Explore en F5 usa `_explore_final_message` sobre `response_output`, distingue `item.completed` tipo `agent_message` y `turn.completed`; pero depende de `output_truncated` global y de un parser textual que no reconoce el token histórico `READY TO PROPOSE` separado por espacios.
5. Propose, Apply y Sync/Archive utilizan un éxito genérico (`_execution_is_successful`) y verificaciones indirectas de artefactos/CLI; la revisión independiente de propuesta y de código invoca `parse_review_verdict(res.full_output)` mezclando logs y respuesta.
6. `OrchestrationRun.stop_details` posee checkpoints de normalización y Explore; el checkpoint Explore de #194 almacena un SHA y contexto pero la reentrada comprueba sobre todo la **forma** del hash, no vuelve a cotejar una evidencia fuente inmutable. La invocación anterior a #194 carece de ese checkpoint; no debe fabricarse.
7. `OpenSpecAdapter.validate_change_strict` usa el CLI instalado con `openspec validate <change> --strict --type change`, no un validador propio. El CLI es gate estructural necesario, no sustituto de pruebas y evidencia de ejecución.

## Decisión D1: separar fuentes de confianza sin crear otro motor

Mantener `CliAgentRunner`, `AgentExecutionResult` y confinamiento como propietarios. Diseñar campos/propiedades tipadas o adaptación pequeña **dentro del contrato existente** que representen:

| Faceta | Significado | Validación |
| --- | --- | --- |
| Ejecución | `exit_code`, `timed_out`, `preflight_error`, error de entorno/credenciales | Rechazo si no hay éxito confirmado |
| Respuesta final autoritativa | Último mensaje de agente/resultado estructurado **íntegro**, extraído de la fuente nativa soportada | Tamaño de bytes y UTF-8, esquema/veredicto cuando aplique, fuente/cierre de turno |
| Diagnóstico | Eventos de herramienta, progreso, stdout/stderr crudos saneados | Truncamiento con bandera independiente; NO confiere autoridad |
| Integridad del resultado | Resultado `COMPLETE`, `MISSING`, `TRUNCATED`, `AMBIGUOUS` o equivalente mínimo | No avanzar cuando la respuesta final o su provenance es incierta |
| Evidencia | Fuente nativa, proveedor/modelo/perfil, workflow (incl. hash), intento, hashes de contexto y respuesta, Run/candidato | Identidad y verificación antes de persistir/reusar |

La elección exacta de tipos no está decidida; **no** añadir una tabla, repositorio, ledger o servicio genérico sin demostrar que los actuales no alcanzan. `output_truncated` podrá seguir existiendo para diagnóstico/compatibilidad; no se le permitirá representar simultáneamente «log abreviado» y «respuesta final inválida».

## Decisión D2: transporte y extracción por proveedor (sin emulación OpenSpec)

- **Codex:** preferir el mecanismo nativo ya utilizado de último mensaje/JSON schema si la versión y el perfil verificados lo permiten. La extracción de NDJSON requiere parsear eventos **completos antes de resumir diagnósticos**, identificar el último `agent_message` autoritativo del turno pertinente, confirmar `turn.completed` sin `turn.failed`, y rechazar NDJSON malformado, incompleto, mezclado o ambiguo. **No** confiar en texto visible dentro de eventos `command_execution`/tool output ni en un `READY_*` copiado desde el Issue.
- **Antigravity:** investigar y verificar el formato/canal auténtico bajo el CLI y perfil instalados antes de definir el parser. No inventar `turn.completed` ni presuponer que ambos proveedores emiten los mismos eventos. Si solo hay salida textual, verificar criterios de terminación/fuente compatibles y reducir el nivel de autoridad permitido cuando no exista respuesta delimitada verificable; nunca asumir éxito de una cita.
- **Canal nativo estructurado:** una salida de respuesta de más de 4.000 caracteres puede seguir siendo íntegra dentro de un presupuesto de bytes seguro, aunque se recorten diagnósticos. Si la salida final supera su límite, se declara inválida; no se aumentan límites indefinidamente.
- Conservar saneamiento de credenciales, aislamiento de procesos y límites de recursos. No guardar transcripciones completas con secretos en PostgreSQL, logs HTTP o GitHub. Registrar hashes, estado, metadatos y resumen saneado mínimo; si una evidencia recuperable persistida es imprescindible, justificar ubicación, ACL, vida útil y ownership exacto antes de implementarla.

## Decisión D3: semántica por etapa y matriz de consumidores

| Etapa/función | Resultado exigible | Evidencia independiente de salida | Política |
| --- | --- | --- | --- |
| Normalizar F4 | JSON/response nativo íntegro y validador Gherkin | fuente Issue + comentarios/provenance y postcondición GitHub | Conservar publicación idempotente |
| Explore | Veredicto final inequívoco `READY TO PROPOSE` (compatibilidad documentada con `_`) o `HUMAN REQUIRED` con opciones originales | exit 0, workflow native, Run/Issue/contexto; checkpoint atado a fuente real | No crear Propose con texto incidental |
| Propose | Fin de ejecución auténtico; artefactos `proposal.md`, `design.md`, `specs/`, `tasks.md` | archivos en Change correcto y CLI strict real PASS | Una salida bonita no reemplaza artefactos |
| Clasificación | Objeto íntegro de complejidad y razones | hashes de artefactos/contexto y perfil | No inferir complejidad por keywords |
| Revisión propuesta | Veredicto estructurado en canal final independiente | revisor independiente, propuesta/SHA, política | No usar stdout+stderr mezclados |
| Apply | ejecución nativa comprobada y código/tests en candidato | diff SHA, pruebas, tareas y permisos | No transición solo por exit code |
| Verify | veredicto JSON final e integridad confirmada | resultados de pruebas, implementación y OpenSpec | Falla cerrada si resultado incompleto |
| Revisión código | revisión independiente estructurada | SHA candidato, hallazgos, separación de autoría | No analizar logs como veredicto |
| Preparador PR1/PR2 | JSON íntegro con título/cuerpo semántico | identidad Run/Issue/PR, SHA, validación de enlaces | No auto-cerrar Issue por keywords |
| Sync/Archive | ejecución native + evidencia de specs sincronizadas y archive correcto | ruta/archivos, verificación CLI, rama doc-close | Sin éxito sintético por stdout |
| Cierre GitHub | API outcome remoto inequívoco | PR1/PR2 merges + issue closure | No inferir éxito desde texto de agente |

**Clave:** contratos específicos por etapa permanecen en el coordinador/validador existente; el runner certifica transporte, no decide semántica OpenSpec ni autorización de negocio.

## Decisión D4: checkpoint/recovery y límites de reentrada

- Usar `OrchestrationRun.stop_details` + repositorios/auditoría existentes, con identidad de Run, Issue, Change, rama/base/candidate, etapa, proveedor/modelo/esfuerzo, workflow_sha256, intento, fuente de respuesta, SHA de respuesta final validada, hash de aclaración y estado de aprobación. La comparación de un SHA de 64 caracteres **no prueba** por sí sola integridad; confrontar contra evidencia de origen o comprobación externa firmemente vinculada al intento.
- Guardar checkpoint/etapa de forma transaccional o con reconciliación explícita antes de ejecutar otro despacho; proteger contra doble llamada desde CLI/API, pérdida de energía y procesos concurrentes. Una transición no debe depender de que el cliente HTTP permanezca conectado.
- Cuando ya existe veredicto válido persistido **del mismo intento/contexto**: reusar sin ejecutar otra inferencia. Cuando hay resultado incompleto/desconocido: pausar y solicitar decisión de recuperación, no repetir automáticamente. Una nueva respuesta humana legitima el contexto siguiente pero no constituye permiso para reutilizar/ver inventar una inferencia previa.
- **Run F5 histórico:** los logs de `task-2931.log` evidencian el texto `READY_TO_PROPOSE` previo, pero no un checkpoint completo. La llamada del 27-10-2026 con `output_truncated` no prueba que su veredicto fuera íntegro. Investigar transcripción de manera **solo lectura** antes de proponer recuperación. No alterar manualmente `stop_details`, no crear otro Run, Issue, Change ni worktree y no despachar agentes hasta la siguiente autorización.

## Decisión D5: seguridad y presupuesto de salida

- Definir dos umbrales independientes: diagnóstico visual acotado y máximo de **respuesta final íntegra** por bytes, con límites de memoria/tiempo de stream por proveedor y rechazos antes de deserializar contenido excesivo. Los valores se seleccionan con evidencias de tamaño reales; no extrapolar 4.000 caracteres de línea a tamaño seguro de respuesta.
- Prohibir secretos, PII no necesaria, tokens, rutas sensibles y prompts completos en eventos de error, telemetría, PR o checkpoints. Redactar datos antes de persistir; evitar hash sobre una transformación no verificable cuando la validación necesita los bytes originales. El proceso de captura no debe permitir pérdida silenciosa de bytes ni bypass de confinamiento.
- Mantener rutas protegidas para response files, symlink guards y limpieza; registro de SHA/ACL sin duplicar transcripción. Diagnóstico truncado puede informar un evento `DIAGNOSTICS_TRUNCATED` pero jamás disparar por sí solo una reejecución o autorización humana de negocio.

## Alternativas rechazadas

1. **Aumentar `MAX_LINE_CHARS` (4000→N):** aplaza el problema y no distingue tool events de decisiones.
2. **Eliminar guard `output_truncated`:** permite que una respuesta final cortada avance en falso.
3. **Cambiar solo `_run_explore`:** deja consumidores `full_output` y revisiones inconsistentes.
4. **Crear `AgentOutputOrchestrator`/motor de parsing universal nuevo:** agrega responsabilidad paralela y no respeta YAGNI.
5. **Reescribir F1–F4 o activar F7:** no tiene relación causal, viola el contrato de fases.
6. **Marcar como recuperados los Explore previos editando DB:** fabricaría evidencia y podría duplicar despachos.

## Secuencia de implantación PROPUESTA (no autorizada todavía)

1. Congelar inventario de consumidores, rutas alcanzables, CLI/perfiles instalados y fixtures reales **saneados**; completar análisis de contrato de AGY y versiones nativas Codex antes de elegir formato de respuesta.
2. Delimitar y especificar contrato de runner compatible hacia atrás, sin tablas/servicios nuevos; vincular pruebas por criterio Gherkin.
3. Ajustar clasificación de salida a respuesta final completa, conservando diagnósticos truncables sin autorizar transiciones; migrar consumidores de `full_output` a lectura confiable cuando deciden gates.
4. Conectar veredictos y artefactos nativos de todas las etapas con integridad y hashes de contexto; verificar reentrada e idempotencia del mismo Run; clasificar casos de evidencia antigua.
5. Ejecutar pruebas de unidad, integración, fixtures NDJSON/text/JSON, regresiones y E2E de proceso real confinado en entorno desechable, con fallos controlados; exigir OpenSpec CLI strict PASS del Change aprobado y candidato, Ruff y diff check.
6. **Solo tras autorización independiente de implementación y, después, de merge/deploy:** publicar, desplegar gobernadamente y continuar una sola vez Run F5 existente, sin scheduler ni fallback, capturar hitos Propose/Apply/Verify/PR1/PR2.

## Riesgos y controles

| Riesgo | Severidad | Control verificable |
| --- | --- | --- |
| Avanzar con respuesta parcial | Alta | respuesta final completa + fuente + validación + negativa en test adversarial |
| Doble consumo Codex al reanudar | Alta | intento y checkpoint durable idempotente; pruebas de crash y doble HTTP |
| Falsa HUMAN_REQUIRED por logs | Alta | parser de canal autoritativo; citas/tool logs negativos |
| Aprobación de review contaminada por stderr | Alta | veredicto estricto solo respuesta final; revisión independiente vinculada a SHA |
| Diferencia entre CLIs | Alta | capability preflight real; rechazo sin formato confirmado |
| Fuga de secretos en diagnóstico | Alta | redacción, límites, test de credenciales/provenance |
| Escribir en Worktree F5 desde reparación | Crítica | validación aislada, cero mutaciones hasta autorización |
| Discrepancia `READY TO PROPOSE` vs `_` | Media | normalización de tokens finales documentados; ejemplos y tests |
| Validación strict que pasa pero E2E falla | Alta | strict es gate necesario, no suficiente; E2E integrado obligatorio |

## Discrepancias aún por resolver antes de implementar

- Contrato rector v1.3 exige un Change por fase; este borrador es **offline** y no constituye un Change de fase adicional. Su integración a un Change autorizado deberá ser gobernada sin romper la reserva `gacela-05-ui-self-hosted` ni su Run. No se publica como nuevo Change ejecutable.
- Verificar formato y capacidad real de Antigravity: el código demuestra resolución nativa y transporte, pero no garantiza su salida terminal. No inventar formatos de evento.
- Verificar la variante exacta del Codex CLI del servidor y sus opciones de resultado final; contrato de salida nativa disponible en algunas llamadas del repo, pero no se ha revalidado en Ubuntu para Explore.
- Reconcilio antes de aplicar la diferencia histórica de comandos strict: el adaptador actual usa `--strict --type change`, aunque algunas specs F3 citan `--strict --no-interactive`. El CLI instalado y el contrato actual prevalecen; ambos deben verificarse en entorno aislado.

## Verificación de aceptación

La validación estructural que debe demostrar el usuario/agente en Ubuntu, en un checkout *desechable*:

```bash
openspec validate f5-agent-result-integrity-design --strict --type change
```

**Criterio:** exit 0, PASS; si falla, ajustar únicamente artefactos de este borrador y repetir validación sin modelo. Después, cuando se incorpore a la ubicación canónica autorizada, volver a pasar strict sobre el Change oficial además de pruebas integradas. No declarar PASS por inspección manual, por este documento o por tests ajenos.
