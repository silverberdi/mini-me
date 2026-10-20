# INSUMO ARQUITECTÓNICO CERRADO PARA EL FUTURO `openspec-propose`

**Tipo de entregable:** contrato de entrada técnico, redactado por ChatGPT después de analizar propósito, decisiones vigentes, servicios y código en GitHub. **NO ES UN `propose`, no contiene artefactos OpenSpec producidos por el agente, no es instrucción para programar y no autoriza ninguna operación.**

**Repositorio/base inspeccionada:** `silverberdi/mini-me` · `main` · `5b0a8736c4efb981549f477a4e8931a96b1168ed` (PR #161). **Change futuro sugerido:** `safe-frozen-candidate-code-review-continuation`. Este nombre solo designa la capacidad; el agente empleará su propio workflow nativo y resolverá la raíz efectiva de OpenSpec al recibir autorización separada de `propose`.

## 0. Instrucción de alcance para quien realice `propose` (no ejecutarla ahora)

Convertir **este contrato íntegro**, incluyendo FCR-01–09, E01–12 y AD-01–06, en **un solo Change vertical, limitado a planificación**, mediante el workflow `openspec-propose`/`opsx-propose` realmente instalado. El trabajo de investigación general, censo y selección de arquitectura **ya está hecho**; **NO** delegar un redescubrimiento global, reescritura de control plane ni implementación. Comprobar únicamente los supuestos puntuales marcados como no observados desde GitHub, y registrar los resultados que materialmente cambien el diseño.

**Valor preciso:** dado un candidato ya congelado y con el *último batch completo de checks* PASS, realizar exclusivamente una CODE_REVIEW independiente con DeepSeek Direct, con autorización one-shot cuando el Run está detenido por gate excepcional; conservar SHA/manifest/generación/Job/historia, registrar revisión completa y gasto, y detenerse en gate humano. Para Runs normales sin gate excepcional, preservar el review autónomo y la continuidad ordinaria bajo política permanente.

**Salida futura del agente, NO de ChatGPT:** `proposal.md`, `design.md`, `specs/**/spec.md`, `tasks.md`; matriz FCR→escenarios E→pruebas→evidencia; Removal Ledger REUSE/MODIFY/REMOVE/RETAIN-WITH-REASON; `openspec validate --strict` o validación nativa equivalente. Terminar **antes** de `apply` y someter la propuesta a revisión arquitectónica humana. No escribir dichos artefactos por fuera del workflow.

### Decisiones de diseño que NO quedan abiertas

1. **Un único entrypoint de control plane** para review-only, con `run:<run_id>` claim, un solo heartbeat propietario, fencing y checkpoint durable. Extender coordinación existente (`RecoveryConvergenceService`/control plane), no crear orquestador paralelo.
2. **Un solo revisor oficial:** `DeepSeekCodeReviewService.review_candidate` vía **DeepSeek Direct**; mantener `review_evidence.validate_review_authority`, preflight fresco, presupuesto/account/identidad/capacidad, snapshot verificado y payload selectivo de PR #155. Claude Code CLI+DeepSeek, OpenRouter, Codex y Antigravity NO suplen la CODE_REVIEW.
3. **Checks:** extraer/reusar la regla de `_validate_current_checks_batch`; exige conjunto completo, nombres/comandos, tiempo, SHA/generación y exit code del lote más reciente. `ControlPlaneService._execute_authorize_deepseek_code_review` hoy acepta cualquier fila PASS y `DeepSeekCodeReviewService._read_exact_checks` puede rechazar históricos fallidos: ambos deben converger a la misma regla. El status público debe reflejar el lote vigente, sin borrar históricos. No interpretar `project.checks` vacío como licencia automática para review-only.
4. **Cierre genuino:** `review_candidate` persiste veredicto/findings/costos, pero la transición definitiva `REVIEW_COMPLETED` y chequeo post-review siguen alojados en el pipeline general. Extraer/reusar **solo** esa finalización segura, con validador de integridad y fencing; nunca cruzar `execute_queued_job`, APPLY, ChecksRunner, auditoría o PR en esta operación excepcional.
5. **Autoridad:** `AUTHORIZE_DEEPSEEK_CODE_REVIEW` existente conserva identidad Run/Job/candidate/base/generación/manifest/account/model/price/expiry/max_spend. La autorización no equivale a ejecución. Vincular atómicamente acción one-shot, reserva, checkpoint y review; no introducir per-call permission en la política ordinaria. Resultado HTTP incierto ⇒ `AMBIGUOUS`/equivalente, sin segundo dispatch ciego ni promesa imposible de exactly-once remoto.
6. **Segunda continuación protegida:** un permiso nuevo y distinto podrá retomar desde validación de CODE_REVIEW ya registrada (`COMPLEMENTARY_REVIEW` o equivalente) sin volver a `IMPLEMENTING` ni checks. En el código actual `_execute_continue` reubica `FREEZING_CANDIDATE` a `IMPLEMENTING`: impedir explícitamente ese recorrido desde `REVIEW_AUTHORIZATION_PENDING`, antes de modificar Job/Run.
7. **Política normativa:** `docs/CANONICAL_DECISIONS.md` (13-oct) + `AGENTS.md` designan DeepSeek Direct reviewer; `openspec/config.yaml` y secciones de `docs/CHANGE_DELIVERY_CONTRACT.md` conservan lenguaje antiguo sobre fallback. En el Change futuro incluir la mínima reconciliación causal de instrucciones activas, no rediseñar política ni otros documentos.
8. **N01 no es plantilla especial:** la capacidad debe ser reutilizable en otros repos administrados. Solo el *piloto intervenido* se detiene tras el dictamen; el pipeline ordinario no debe perder autonomía, ni sumar una aprobación humana ficticia.

### Intervenciones acotadas según lectura directa (SHA indicado)

| Código existente | Observación verificada | Diseño que deberá expresar OpenSpec |
|---|---|---|
| `control_plane_service.py::_execute_continue` | Desde freeze puede forzar `IMPLEMENTING`, Job `RUNNING` | Guard fail-closed antes de mutación; nueva continuación review-only separada |
| `control_plane_service.py::_execute_authorize_deepseek_code_review` | Guarda acción durable y acepta checks PASS parciales | Reusar acción y selector de batch completo; no disparar modelo dentro del simple authorize |
| `recovery_convergence_service.py::recover_checks_only` | Patrones de claim/heartbeat/fence ya operan | Reusar exclusivamente gobernanza, no repetir checks |
| `orchestration_service.py::_validate_current_checks_batch` | Selecciona K resultados más recientes y valida lote | Regla autoritativa compartida con autorización/reviewer/status |
| `orchestration_service.py::get_status` | Acumula resultados históricos | Exponer último lote vigente y dejar histórico auditable |
| `deepseek_code_review_service.py::review_candidate` | Revisión directa; persiste verdict, findings y costes; deja `REVIEW_RUNNING` hasta finalización posterior | Reusar motor oficial y finalizar sin pipeline general |
| `execution_pipeline.py::execute_queued_job` | Ejecuta checks y puede reentrar APPLY; contiene finalización post-review segura | No llamarlo para review-only; extraer solo finalizador/validación compatible |
| `orchestration_service.py::COMPLEMENTARY_REVIEW` | Valida CODE_REVIEW persistida y avanza a auditoría/PR/remediación | No equivale a dispatch de revisión; reentrada posterior requiere gate separado |
| `budget_service.py::reserve_review_budget` + `review_evidence.py::validate_review_authority` | Presupuesto/autoridad existentes | Reusar sin presupuesto paralelo ni nuevo validador |

### Solo dos comprobaciones de entorno aún abiertas

- **DB N01 read-only:** confirmar si check histórico fallido realmente comparte SHA/generación del último batch PASS y establecer el ID/hash exactos de manifest y autoría desde los registros durables; el reporte SSH previo no prueba por sí solo todos estos cruces.
- **Concurrencia/linkage:** verificar el modelo real de `OperatorActionRecord`, presupuesto/reservas y semántica de crash/claim, para escoger el punto de consumo duradero del permiso sin doble despacho. No tocar registros; un SELECT focalizado o lectura de repositorios/modelos basta para planificar.

### Gates de no-regresión y de ahorro

**FCR-01…FCR-09 y E01…E12 abajo son obligatorios** y deben tener traza explícita. Especialmente E06 (claim/timeout/concurrencia), E10 (CONTINUE genérico peligroso), E11 (flujo autónomo normal) y E12 (**solo postdeploy expresamente autorizado**). Durante `propose`: **cero** llamadas pagadas DeepSeek, cero APPLY, cero ejecución de `pytest -q` N01, cero PR/merge, cero deploy, cero scheduler, cero escrituras DB/Run/Job. Probar más tarde con Git+PostgreSQL reales y HTTP DeepSeek interceptado; una prueba simulada jamás se presenta como E2E productivo.

**N01 — aceptación futura, sin ejecución ahora:** Run `8e7ebec8-9eff-478b-bae3-cf686ea91be2`, Job `b917a9f0-0354-4805-863f-7ab4e7ada559`, candidato `2fcad0ef73eb4766ca1bb6249a081cb4070ecced`, último lote `pytest -q` 16 PASS según informe SSH 20-oct, CODE_REVIEW aún ausente según el mismo informe, scheduler deshabilitado. Preservar todo; autorización anterior de checks-only está consumida; la autorización verbal de CODE_REVIEW no es un `OperatorActionRecord` durable.

**Jerarquía:** prevalece la intención de producto y las decisiones canónicas vigentes sobre comentarios históricos y docs desactualizados. Si un hecho nuevo contradice este insumo, reportar exactamente archivo/fila/impacto y ajustar mediante `update` OpenSpec cuando corresponda; nunca improvisar implementación ni cambiar el producto.

---

# PARTE III — ESPECIFICACIÓN TÉCNICA ÍNTEGRA YA PREPARADA PARA EL SIGUIENTE CHANGÉ OPEN SPEC

> **Estado:** documento técnico previo a OpenSpec, no propuesta aprobada ni acción autorizada. Base analizada: PR #161 merge SHA `5b0a8736c4efb981549f477a4e8931a96b1168ed`. Incluido íntegro para que la nueva conversación NO dependa de un enlace ni necesite repetir el censo.

# mini me — Contrato técnico previo a OpenSpec
## Safe Frozen-Candidate CODE REVIEW Continuation

**Estado:** alcance propuesto, NO OpenSpec `proposal/design/specs/tasks` generado ni aprobado; no implementación ni mutación del repositorio.

**Base de análisis:** código de `silverberdi/mini-me` en el *merge commit desplegado* `5b0a8736c4efb981549f477a4e8931a96b1168ed` (PR #161). Esta especificación nace de lectura de archivos reales en GitHub. La observación de PostgreSQL y del worktree del piloto procede del reporte SSH READ-ONLY aportado por el operador, no de una lectura autónoma del servidor por ChatGPT.

**Caso de aceptación en producción, sin autorizar su ejecución todavía:**
- Host Ubuntu: `192.168.0.194`; aplicación `/opt/minime/app`.
- Proyecto `mini-me-fixture`, Change `sanitize-filename-token`.
- Run `8e7ebec8-9eff-478b-bae3-cf686ea91be2`: `FREEZING_CANDIDATE`, inactivo, `NEEDS_HUMAN`, `stop_details.code=REVIEW_AUTHORIZATION_PENDING`.
- Job `b917a9f0-0354-4805-863f-7ab4e7ada559`: `CHECKS_PASSED`.
- Candidate `2fcad0ef73eb4766ca1bb6249a081cb4070ecced`, congelado; manifest hash con prefijo `422f505` (el ID completo y hash deben verificarse, NO inferirse).
- Último lote autoritativo: `pytest -q`, exit code `0`, **16 passed**. Existe resultado histórico fallido por ambiente; debe preservarse.
- `CONTRACT_REVIEW` completada/aceptada; `CODE_REVIEW` no ejecutada ni persistida. Autoría real debe leerse de la fuente durable (último reporte: `codex`, no mixed).
- DeepSeek Direct es el revisor obligatorio. Claude Code CLI conectado a DeepSeek NO sustituye su cuenta, identidad, liquidación ni registro de resultado en mini me.

## 0. Contexto de producto y posición real de este cambio (autoridad superior al código)

### 0.1 Para qué existe mini me

Según `docs/BUSINESS_INTENT.md` y `docs/ARCHITECTURE.md`, **mini me es un plano de control personal que coordina el trabajo de agentes de programación**, no una IA que programe por sí misma, ni un reemplazo de OpenSpec, ni un producto comercial. Una sola instalación Linux debe recibir una necesidad desde GitHub o un Change OpenSpec READY y llevarla, con **mínima mensajería humana**, hasta código real implementado por un agente usando OpenSpec nativo, checks verificables, revisión independiente, PR y —tras merge humano y autorizaciones correspondientes— cierre OpenSpec/despliegue observado. La métrica no es cantidad de líneas, clases, tests ni cambios cerrados: es **valor funcional reproducible**, operable y auditable, con bajo consumo innecesario de cuota y sin pérdida de trabajo tras interrupciones.

**Responsabilidades innegociables:**

| Límite | Autoridad | Consecuencia para este Change |
|---|---|---|
| Intención, prioridades, decisión de producto, gasto extraordinario, merge y decisiones irreversibles | Propietario humano | No inventar nuevas aprobaciones rutinarias ni interpretar CODE_REVIEW como permiso para APPLY, PR o merge. |
| Contratos de comportamiento y workflows semánticos `propose/update/continue/apply/verify/sync/archive` | OpenSpec ejecutado por agentes autorizados | `mini me` no escribe specs/código como sustituto del agente; la propuesta nace por workflow nativo. |
| Implementación, edición y verificación mediante OpenSpec | Codex / Antigravity según capacidad/perfil de etapa | La revisión del candidato **no** dispara al ejecutor, APPLY ni replanificación. No imponer roles perpetuos. |
| CONTRACT_REVIEW y CODE_REVIEW independientes, read-only | DeepSeek **Direct** por cuenta/API/identidad autorizadas | El Claude Code CLI conectado a DeepSeek es una herramienta local auxiliar de inspección; su salida **no** sustituye evidencia CODE_REVIEW durable. OpenRouter nunca revisa. |
| Estado operacional, gates, cuotas, selección de etapa, claims/fences, invocación, evidencias y reconciliación | Daemon/API de mini me y PostgreSQL | Una continuación *review-only* es una responsabilidad del control plane existente, no un segundo coordinador ni un atajo SQL. |
| Identidad de repositorio, rama, base y candidato; Issues/PRs y aprobación de merge | Git/worktrees y GitHub, cada uno en su frontera | El SHA local de un Mac o un GitHub Issue no prueba el candidato preservado del host Linux. |
| Observabilidad y acciones guiadas | UI/API/CLI sobre el mismo estado operativo | Mostrar qué hace, qué hizo, qué viene y qué requiere intervención, sin mentir sobre PASS o READY. Mobile: observabilidad/atención; tablet: operación; web: control center. |

### 0.2 En qué punto del roadmap estamos y qué no se debe adelantar

`docs/ROADMAP.md` y `docs/BACKLOG.md` ordenan un camino por **valor vertical**: **R01** primer agente real → OpenSpec → revisión independiente → PR; **R02–R03** intake GitHub y cola autónoma; **R04–R05** cierre y recuperación durables; **R06–R07** capacidades contextuales y control operacional; **R08–R09** segundo repositorio y evolución gobernada; **R10** autodesarrollo con merge humano. No se debe transformar una recuperación de R01 en un proyecto paralelo de UI, infraestructura, orquestador genérico o funcionalidad de etapas futuras.

**N01 es el experimento productivo que debe demostrar R01 de extremo a extremo**, no una nueva iniciativa ni un objetivo de «hacer pasar 16 tests». El Change presente debe cerrar **la discontinuidad de un checkpoint legítimo** sin descartar ningún avance y, a la vez, dejar una capacidad reutilizable para futuros candidatos de otros repositorios. El resultado inmediato es una CODE_REVIEW realmente registrada del SHA congelado; el objetivo de R01 sigue siendo llegar después a un **PR auténtico y verificable** bajo las restantes autoridades. No declarar R01 `DONE` por completar CODE_REVIEW ni activar R02 anticipadamente.

**Estado actual verificado por distintas fuentes, sin confundirlas:** PR #161 de corrección del control plane ya fusionado/desplegado (reporte del operador); N01 preservado en Ubuntu con Run/Job/candidato congelado y último lote de 16 checks aprobado (reporte SSH); la CODE_REVIEW oficial todavía no existe. El scheduler permanece **disabled/inactive intencionalmente**; el checkout gestionado no es el mismo árbol que `/opt/minime/app`, y existen archivos OpenSpec ajenos al candidato que deben conservarse. Las evidencias previas de CONTRACT_REVIEW no autorizan ni acreditan CODE_REVIEW.

### 0.3 Diferencia entre política operativa ordinaria y piloto intervenido

El producto aspira a **autonomía bajo políticas previamente aprobadas**. `docs/CANONICAL_DECISIONS.md` (política vigente 2026-10-13) y `docs/PROVIDER_POLICY.md` permiten llamadas DeepSeek Direct ordinarias cuando las políticas del propietario, la compatibilidad, cuenta y saldo lo permiten, **sin pedir un permiso monetario por cada llamada ni exigir tope opcional inexistente**. Sin embargo, **N01 permanece intencionalmente detenido en un gate humano excepcional**, con una autorización específica y de una sola ejecución para revisión. Estas dos reglas deben coexistir:

- **Piloto N01:** respetar la autorización humana exacta de CODE_REVIEW, su alcance y expiración, el presupuesto vigente y la orden de detenerse **después** del veredicto sin continuar por cuenta propia a auditoría/PR/remediación. No ejecutar pruebas completas mediante DeepSeek ni repetir los 16 checks.
- **Camino autónomo ordinario:** mantener la posibilidad de pasar de checks aprobados a CODE_REVIEW y, si procede, al siguiente stage por política normal **sin introducir un gate humano artificial por cada revisión**. No exigir a todos los Runs la autorización one-shot excepcional creada para N01. Esto se prueba como regresión positiva, no solo como negación de side effects.

La condición `NEEDS_HUMAN` solo procede para decisiones humanas reales. Una restricción de capacidad debe dejar espera operable; un fallo recuperable no debe convertirse en una cadena de «pide autorización otra vez» cuando existe política durable suficiente. Lo que se necesita preservar es la **autoridad**, no perpetuar los bloqueos del primer piloto.

### 0.4 Criterio sistémico para aprobar el diseño

El diseño OpenSpec debe demostrar que el *mismo* servicio y las *mismas* autoridades se mantienen coherentes a lo largo del trayecto **OpenSpec/GitHub → Run/Job → worktree/candidate → checks → CODE_REVIEW → etapa siguiente → PR → merge humano → sync/archive/despliegue/E2E**. Este Change interviene **solo** la transición entre candidato ya congelado y revisión válida, pero no puede romper las demás. Por tanto debe incluir:

1. **Trazabilidad vertical:** intención de «sin handoffs humanos innecesarios» → capacidad de recuperar una etapa preservada → SHALL/SHALL NOT → prueba de código/DB/Git → resultado observable en la API/UI/CLI y en el piloto cuando su ejecución sea autorizada.
2. **Fronteras:** no sobreescribir Git/Worktree, no reprogramar el daemon ni OpenSpec, no segundo reviewer runner, no duplicar selección de checks, claims ni política de gasto. Un servicio existente debe seguir siendo fuente de verdad por cada responsabilidad.
3. **Costo y fiabilidad:** una inferencia máxima por autorización/identidad válida; usar diff acotado; nunca repetir tests ni APPLY **para recuperar esta etapa**; si el resultado HTTP pudo ser facturado pero no hay confirmación, checkpoint ambiguo y **observación antes de cualquier retry**. El flujo ordinario conserva sus pruebas requeridas en su momento normal.
4. **Operación real:** UI en español y canales de observabilidad existentes revelan candidato, checks vigentes frente a históricos, revisión pendiente/ejecutada y siguiente paso autorizado. El teléfono no necesita operar todo; no introducir una PWA nueva por este arreglo.
5. **E2E verdadero y regresiones:** fixture desechable con PostgreSQL y Git/worktree reales, HTTP de revisión interceptado en tests para no facturar, pruebas negativas de fencing y side effects, comprobación del camino autónomo estándar, y luego piloto/despliegue solo con aprobaciones separadas. Unit PASS no reemplaza evidencia productiva.
6. **Cierre de ingeniería:** inspección de callers/writers, matriz REUSE/MODIFY/REMOVE/RETAIN-WITH-REASON; retirar código muerto introducido/sustituido si es seguro y verificar tras el retiro. Evitar abrir bugs cosméticos no causales o extensiones de R02–R10.

**Precedencia y discrepancias de documentos:** consultar explícitamente `docs/BUSINESS_INTENT.md`, `docs/CANONICAL_DECISIONS.md`, `docs/PRODUCT.md`, `docs/ROADMAP.md`, `docs/BACKLOG.md`, `docs/ARCHITECTURE.md`, `docs/AGENT_CONTRACTS.md`, `docs/CHANGE_DELIVERY_CONTRACT.md` y `docs/ENGINEERING_DISCIPLINE.md`. Algunas fichas del backlog aún dicen `PLANNED` y algunas líneas históricas de PRODUCT/ARCHITECTURE describen a los agentes primarios como revisores o a DeepSeek como fallback; **no convertir esas frases antiguas en un cambio implícito del contrato posterior que designa DeepSeek Direct para ambas reviews**. Distinguir política vigente de documentación histórica y reportar cualquier contradicción material, sin reescribir silenciosamente documentos no causales.

## 1. Problema y valor observable

**Antes:** un candidato que ya superó checks y fue congelado tras `recover-checks` queda en `REVIEW_AUTHORIZATION_PENDING`. La acción de autorización de gasto no despacha la revisión. Continuar por el recorrido genérico puede volver a `IMPLEMENTING` y provocar un nuevo APPLY o más checks. El servicio de revisión también puede rechazar un lote vigente por mezclar fallos históricos del mismo SHA/generación.

**Después:** mini me permite, mediante la autoridad humana exacta **cuando exista un gate como el de N01** y una sola ruta canónica, ejecutar **únicamente** la revisión `CODE_REVIEW` de ese candidato congelado con DeepSeek Direct, aprovechar el lote de checks vigente sin repetirlo, persistir veredicto/uso/evidencia ligados a SHA+generación+manifest y detenerse en el gate humano propio **de este piloto** antes de cualquier otra etapa. Para otros Runs ordinarios, el camino autónomo aprobado conserva su continuidad; el nuevo mecanismo no introduce una aprobación humana obligatoria por cada review.

**Métrica de éxito en N01:** 1 candidato conservado, 1 revisión como máximo, 0 APPLY, 0 checks repetidos, 0 cambios de archivo/código del candidato, 0 cambios de generación y 0 etapas posteriores ejecutadas sin permiso; resultado auditable en PostgreSQL y UI/API/CLI. **Métrica de regresión de producto:** un Run normal con políticas autorizadas continúa a las etapas legítimas sin un gate humano adicional inventado por esta reparación.

## 2. Censo de implementación comprobado (evita redescubrimiento)

| Archivo y símbolo | Estado observado en SHA desplegado | Decisión de alcance |
|---|---|---|
| `src/minime/services/control_plane_service.py :: _execute_authorize_deepseek_code_review` (aprox. 1379–1640) | Confirma candidato+manifest, checks aprobados y límite/fecha/snapshot; guarda `OperatorActionRecord`. **No llama al reviewer**. | REUTILIZAR como autorización durable; no confundir con ejecución. |
| `src/minime/services/control_plane_service.py :: _execute_continue` (988–1060) | En `NEEDS_HUMAN`, limpia el gate, marca Job `RUNNING` y para `FREEZING_CANDIDATE` reubica stage/resumable a `IMPLEMENTING`. | NO INVOCAR desde este checkpoint como mecanismo de review. Asegurar un guard explícito de prohibición de continuación genérica potencialmente destructiva. |
| `src/minime/services/recovery_convergence_service.py :: recover_checks_only` (1043–1277) | Ya tiene claim `run:<id>`, heartbeat de propietario único, fence, decisión durable, limpieza del heartbeat. | REUTILIZAR el patrón de gobernanza para operación *review-only*; NO reutilizar ejecución de checks. |
| `src/minime/services/recovery_convergence_service.py :: request_run_continuation` (1281+) | Reentra al coordinador general, no se limita a `CODE_REVIEW`. | NO usar para dispatch review-only salvo que un contrato acotado pruebe que no alcanza APPLY/checks/auditoría/PR. |
| `src/minime/services/orchestration_service.py :: resume` (448–595), `FREEZING_CANDIDATE` (2110+), `COMPLEMENTARY_REVIEW` (2146+) | `FREEZING_CANDIDATE` congela o reusa; `COMPLEMENTARY_REVIEW` **valida** revisión persistida y decide remediación/auditoría/PR, pero no despacha DeepSeek. | Mantener roles de stage, sin asumir que cambiar directamente a `COMPLEMENTARY_REVIEW` ejecutará revisión. |
| `src/minime/services/execution_pipeline.py :: execute_queued_job` (890–1035, 2322–2835) | El bypass de APPLY requiere `CODE_REVIEW` previo `REVIEW_RUNNING` e identidad exacta; el mismo flujo **invoca `ChecksRunner`** antes de revisión y crea un placeholder. | NO derivar una ruta review-only atravesando ese flujo. Extraer/reusar únicamente colaboradores seguros, sin duplicar semántica de APPLY ni checks. |
| `src/minime/services/deepseek_code_review_service.py :: review_candidate` (90–550) | Ya valida identidad, Git y manifest, autoría independiente, cuenta DeepSeek Direct, capacidad fresca, precio, payload compacto, despacho, respuesta, registro y uso. | REUTILIZAR, nunca escribir un segundo cliente/rutina de DeepSeek ni enviar todo el repositorio. |
| `src/minime/services/deepseek_code_review_service.py :: _read_exact_candidate` (565–755) | Revalida árbol/manifest y selecciona diff y OpenSpec activo, con redacción y límites de entrada. | RETENER sin reimplementar. |
| `src/minime/services/deepseek_code_review_service.py :: _read_exact_checks` (756–776) | Filtra por Job+SHA+generación, **pero rechaza si cualquier resultado histórico coincidente tiene exit!=0**. | CAMBIAR para consumir únicamente el lote autoritativo vigente. |
| `src/minime/services/orchestration_service.py :: _validate_current_checks_batch` (3386–3450) | Ya selecciona los K resultados más recientes del candidato/generación, coteja nombres/comandos, ausencia de duplicados, ventana temporal y exit=0. | REUTILIZAR/EXTRAER como **única regla determinística compartida**, no crear otra selección. No tomar automáticamente la rama `project.checks` vacío => success como habilitación para review-only. |
| `src/minime/services/orchestration_service.py :: get_status` (2762+) | Resumen de checks agregado sobre **todas** las filas del Job, no solamente último lote del candidato. | AJUSTAR visualización de checks vigente con el mismo selector; conservar histórico accesible. |
| `src/minime/services/budget_service.py :: reserve_review_budget` (206+) | Admite política permanente con límites monetarios opcionales y reserva cuando procede; no consume por sí mismo un `OperatorActionRecord` one-shot. | CONSERVAR política general; para la ruta humana excepcional verificar vínculo exacto a autorización one-shot y límite vigente **sin obligar per-call a todos los runs**. |
| `src/minime/services/review_evidence.py :: validate_review_authority` (inicio) | Ya comprueba CODE_REVIEW directa, cuenta/facturación, evidencia de costo y binding al SHA/manifest/generación. | REUTILIZAR para verificar resultado persistido; no inventar un segundo validador de veredictos. |

**Hipótesis que requieren solo comprobación focalizada (no discusión amplia de arquitectura):** determinar si el resultado histórico fallido de `pytest` coincide exactamente con **el mismo SHA y generación** del lote vigente, y cómo se representa el `OperatorActionRecord` de autorización al invocar el servicio (hoy el service guarda `budget_authorization_id=None`). Se inspecciona con SELECTs focalizados durante `propose`, sin borrar ni corregir evidencia histórica. Si esas condiciones difieren, adaptar el diseño manteniendo los invariantes, no ampliar el proyecto.

## 3. Arquitectura requerida (una sola responsabilidad nueva)

**Crear una capacidad de continuación `frozen-code-review-only` de carácter general, no un script `N01-only`.** Elegir una sola fachada canónica accesible desde las interfaces operativas existentes (control plane y/o CLI) y reutilizar los servicios actuales. No agregar nuevo scheduler, nuevo motor de reviews, nuevo cliente DeepSeek ni modelo de datos si los existentes bastan.

**Llamada lógica requerida:**

1. Observar autorización del dueño mediante el mecanismo `AUTHORIZE_DEEPSEEK_CODE_REVIEW` cuando se trate de un Run parado por `REVIEW_AUTHORIZATION_PENDING`; validar identidad de Run/Job/candidate/generación/manifest, cuenta, importe y expiración; no admitir un permiso expirado, ajeno o ya consumido. Los parámetros del permiso existente son `max_spend_usd`, `expires_at` (no superior a una hora) y `pricing_snapshot_id`. La estimación previa USD 0.14114688 **no es precio fijo ni cargo confirmado**: recalcular con el snapshot y payload vigente. Preservar la política general de autonomía ordinaria.
2. Tomar un claim exclusivo `run:<run_id>` mediante gobernanza existente y heartbeat de un solo propietario, con fencing. Si hay competencia, trabajo activo, checkpoint ambiguo, gasto sin conciliar o resultado previo, parar y observar en vez de reintentar.
3. Validar exactamente el checkpoint: Run parado `FREEZING_CANDIDATE`/`NEEDS_HUMAN`/`REVIEW_AUTHORIZATION_PENDING`, Job `CHECKS_PASSED`, proyecto/change/base SHA, candidato congelado+manifest coincidente, generación correcta, worktree real administrado y limpio, SHA/ref Git intactos, atribución e independencia.
4. Seleccionar **solo** el último lote completo vigente mediante la regla canónica existente. Un resultado histórico anterior fallido no equivale al último lote fallido. No admitir lotes incompletos, mezcla de lotes, comandos distintos o evidencias de otros SHA/generaciones. Nunca rerun del `ChecksRunner` ni `pytest` para probar esta etapa.
5. Ejecutar por una sola ruta `DeepSeekCodeReviewService.review_candidate` sobre el candidato congelado con `deepseek-flash`/esfuerzo del perfil vigente, mediante DeepSeek Direct. Dentro del servicio debe mantenerse preflight fresco y cuenta real, factura direct account, precio y presupuesto, independencia, payload acotado y veredicto estructurado. Si no existe una autorización one-shot compatible, bloquear antes de la invocación para este checkpoint.
6. Persistir revisión y findings autoritativos, y liquidar uso real (o registrar reserva/consumo ambiguo sin reenvío ciego). Anexar lineage de operación one-shot cuando aplique, sin inventar capacidad de cancelación de llamadas facturables.
7. Cerrar claim/heartbeat con fencing y dejar Run **detenido bajo gate humano**, con código y resumen inequívocos de: `CODE_REVIEW_COMPLETED_READY_TO_MERGE`, `CODE_REVIEW_COMPLETED_CHANGES_REQUIRED` o `CODE_REVIEW_BLOCKED/AMBIGUOUS` (nombres concretos a decidir dentro de los tipos existentes si se evita nueva enumeración). `READY_TO_MERGE` del revisor **no equivale a autorización humana de merge**. No cambiar el status a `DONE`, no disparar auditoría ni PR.
8. Proveer una ruta de **continuación posterior explícita** que, cuando el humano la autorice en otro momento, reutilice la revisión persistida y empiece en la etapa de **validación de revisión** (`COMPLEMENTARY_REVIEW` o equivalente) sin regresar a APPLY/Checks. Si existen `CHANGES_REQUIRED`, la remediación es otra autorización/decisión, no automática. Sin esta garantía se dejaría el próximo bloqueo estructural preparado.

**Contratos de idempotencia:** ante el mismo Run/Job/SHA/generación/manifest, un segundo dispatch nunca factura dos veces; veredicto `REVIEW_COMPLETED` reutiliza registro sin invocar modelo; checkpoint `REVIEW_RUNNING` con envío posiblemente realizado se considera AMBIGUOUS/WAITING hasta reconciliación autoritativa. No hacer `reset`, `force push`, `checkout`, `git clean`, `worktree prune`, recreación de Jobs ni reescritura de historia.

## 4. Requisitos funcionales verificables (SHALL / SHALL NOT)

**FCR-01 — Readiness exacta.** GIVEN `FREEZING_CANDIDATE` + `REVIEW_AUTHORIZATION_PENDING` + `CHECKS_PASSED` + manifest, worktree y autoridad válidos, WHEN el operador habilita la acción one-shot y ordena review-only, THEN permite solo la revisión ligada al SHA/generación y no altera candidato/Job attempts.

**FCR-02 — Aislamiento de efectos.** El runtime SHALL NOT invocar `execute_queued_job`, native OpenSpec APPLY, Codex, AGY, OpenRouter, `ChecksRunner`, auditoría, PR, merge, scheduler o despliegue durante la operación review-only; SHALL detenerse inmediatamente tras dictamen/espera/bloqueo. Pruebas con sentinelas que fallen si una de esas rutas se llama.

**FCR-03 — Checks históricos.** GIVEN un `CheckResult` histórico fallido del mismo Job, SHA y generación y un lote posterior completo y aprobado, WHEN se prepara la revisión, THEN se reutiliza **solo** el lote posterior sin que el resultado histórico invalide la autorización; historical rows stay unchanged.

**FCR-04 — Rechazo de lote adulterado.** GIVEN falta un check, hay duplicación, comando distinto, evidencia antigua reciclada, SHA/generación errónea o fallos en el lote más reciente, THEN DENY sin modelo ni DB review `COMPLETED`.

**FCR-05 — Cuenta, presupuesto e independencia.** GIVEN cuenta, modelo, esfuerzo, saldo, price snapshot, política o autorización one-shot no compatibles o caducados, THEN BLOCK/WAIT sin factura ni sustitución de modelo. SHALL NOT trasladar API key a OpenRouter ni exponer secretos; preservar política permanente de límites opcionales para flujo ordinario.

**FCR-06 — Salida real.** GIVEN respuesta válida DeepSeek Direct, THEN guardar `reviews.review_stage=CODE_REVIEW`, provider, account fingerprint, billing_origin, model, SHA/base/generation/manifest, status, structured verdict/findings y contabilización de uso/costo verificable; enlazar la autorización cuando corresponda; verificar autoridad con `review_evidence.validate_review_authority`.

**FCR-07 — Fallas/ambigüedad.** GIVEN corte de red tras dispatch, pérdida de claim, crash, doble pulsación, respuesta inválida, agotamiento de capacidad o presupuesto, THEN conservar candidato, evitar repeticiones facturables no demostradas e informar la razón y el destino de recuperación segura. Fencing perdido: no escribir resultados protegidos después de perder autoridad.

**FCR-08 — UI/API/CLI honestos.** Estado visible: `CHECKS_PASSED` vigente y review `PENDING/RUNNING/COMPLETED/BLOCKED` real, distinguiendo históricos. Acción de autorizar no puede presentarse como revisión terminada. No inventar badges de éxito.

**FCR-09 — Siguiente gate controlado, sin degradar autonomía.** GIVEN `READY_TO_MERGE` de DeepSeek en **N01 intervenido**, THEN N01 queda detenido para decisión humana del piloto; el avance posterior puede usar la revisión válida sin retornar a APPLY/pytest. GIVEN `CHANGES_REQUIRED` en N01, no hay remediación autónoma **bajo esta autorización limitada**. GIVEN un **Run ordinario** con política autónoma vigente, THEN mantiene su continuación segura normal a auditoría/PR o remediación gobernada conforme a los gates ya aprobados, sin introducir una confirmación humana por cada review. Ninguna revisión autoriza merge.

## 5. Escenarios mínimos de aceptación

| ID | Escenario | Resultado esperado |
|---|---|---|
| E01 | Checkpoint equivalente a N01 en PostgreSQL+Git real, ya congelado con lote aprobado e histórico fallido | Un solo CODE_REVIEW directo (HTTP interceptado en pruebas) y verdict durable. 0 APPLY/0 checks. |
| E02 | Autorización ausente, caducada, de otra cuenta, monto insuficiente o snapshot incorrecto | Rechazo antes de enviar modelo. |
| E03 | Histórico fallido del mismo SHA/generación seguido de lote vigente completo PASS | Review lee exclusivamente lote vigente; histórico inalterado; dashboard `checks_status=PASSED`. |
| E04 | Solo fallos históricos o último lote incompleto/fallido/adulterado | BLOCKED, sin modelo, sin falso PASS. |
| E05 | Candidato SHA/base/manifest/gen/ownership/worktree limpio ausente o diferente | BLOCKED; ningún efecto fuera de evidencia de rechazo. |
| E06 | Dos disparos concurrentes, comando repetido, crash tras dispatch, timeout de DeepSeek, pérdida de lease/fence | Máximo un dispatch verificable; sin reintento ciego ni doble cargo. |
| E07 | DeepSeek `READY_TO_MERGE` en N01 bajo permiso excepcional | Revisión guardada, gate humano del piloto, sin auditoría/PR/merge autónomos; siguiente operación posterior validada seguro. |
| E08 | DeepSeek `CHANGES_REQUIRED` / hallazgos en N01 | Revisión y findings guardados; candidato intacto, sin APPLY automático bajo permiso limitado. |
| E09 | Ausencia/mismatch DeepSeek Direct/account/model/effort/budget o reviewer no independiente | BLOCK/WAIT, sin sustituir por Claude Code CLI, Codex, AGY u OpenRouter. |
| E10 | Actual `CONTINUE` genérico en `REVIEW_AUTHORIZATION_PENDING` | Fail-closed antes de volver a `IMPLEMENTING` o de reescribir Job. |
| E11 | Regresión de flujo ordinario y `recover-checks` | Un Run normal autorizado sigue desde checks a review y etapas legítimas sin permiso humano ad hoc; recover-checks sigue deteniéndose donde corresponde. No introducir gates ni tests duplicados en producción. |
| E12 | Post-deploy piloto explícitamente autorizado, N01 real | Una sola revisión oficial del SHA, sin nueva suite de tests ni APPLY; reporte durable de gasto/veredicto. No ejecutar E12 durante PROPOSE/APPLY. |

**Pruebas existentes a ampliar, no reemplazar:** `tests/test_deepseek_code_review_postgres.py`, `tests/test_deepseek_code_review_service.py`, `tests/test_pilot_checks_recovery_postgres.py`, `tests/test_orchestration_coordinator.py`, y las pruebas de `control_plane_service` / `review_evidence` pertinentes. En ingeniería pueden correrse pruebas determinísticas focalizadas y gates de regresión; está prohibido usar DeepSeek para ejecutar una suite completa de tests del producto. Pruebas de inferencia usan respuesta simulada o HTTP interceptado; cualquier llamada real posterior exige autorización y costo propios.

## 6. Archivos previstos y límites

**Cambios esperables, con justificación puntual:**
- `src/minime/services/recovery_convergence_service.py`: entrada *review-only* bajo claim/heartbeat o servicio nuevo mínimo delegado desde esta frontera.
- `src/minime/services/control_plane_service.py`: impedir `CONTINUE` peligroso desde review-hold; enlazar autorización y operación de un solo uso con misma identidad; no alterar los comportamientos ordinarios.
- `src/minime/services/orchestration_service.py`: exponer selector canónico de lote actual; hacer estado observacional coherente; reentrada posterior controlada de etapa validación del review.
- `src/minime/services/deepseek_code_review_service.py`: consumir selector autoritativo y, cuando corresponda, validar/linkear autorización exacta; conservar payload y runner.
- `src/minime/services/execution_pipeline.py`: únicamente si requiere extraer colaboradores seguros o cerrar ruta de reentrada; **no** añadir otro APPLY/checks ni reconstruir el pipeline.
- `src/minime/cli/main.py` y controlador API/UI existentes: exponer una sola acción operable sin duplicar lógica; mantener interfaz española.
- Pruebas focalizadas de integración, regresión adversarial, OpenSpec y evidencia.

**No goals:** no nuevo proveedor, no scheduler, no optimizador de modelos, no nueva UX general, no nueva arquitectura de budget, no migraciones DB salvo imposibilidad demostrada con modelos actuales, no PR automático **dentro de la recuperación específica N01** (sin bloquear el PR automático del ciclo ordinario), no solucionar deuda no causal, no modificar `sanitize_filename_token`, no barrer repositorios ni limpiar archivos OpenSpec ajenos. Aplicar Removal Ledger a cualquier ruta sustituida y retirar código muerto solo si el cambio realmente lo introduce.

## 7. Gates de entrega y disciplina OpenSpec

1. **PROPOSE:** el agente debe producir artefactos OpenSpec nativos coherentes usando este contrato como fuente de alcance, no usarlo para escribir código. Solo se permite ajustar design ante contradicción demostrada contra el commit real; emitir delta preciso y evidencia, sin reiniciar exploración amplia.
2. **REVIEW DE PROPUESTA:** validar que la traza FCR→E→test cubre todos los invariantes, incluidos gasto y one-shot, que el flujo no ejecuta APPLY ni checks y que no confunde aprobación de DeepSeek con merge humano.
3. **APPLY (por separado):** solo tras autorización; implementación acotada, pruebas funcionales con PostgreSQL desechable y Git real, garantías de fence y contención, E2E de etapa sin gastar inferencia innecesaria; no deshabilitar test suite para pasar checks.
4. **MERGE/DEPLOY (separados):** PR y merge humanos, respaldo/rollback, despliegue controlado, `minime-scheduler.service` inactivo/deshabilitado. No tocar checkout gestionado ajeno a la app ni destruir N01.
5. **N01 REVIEW REAL (por separado):** re-observar SHA/manifest/autoridad/precio/capacidad y gastar **una sola** llamada autorizada DeepSeek Direct. Detener después del resultado y demostrar integridad de Run/Job/worktree.

**Criterio de no aceptación:** documentación sin E2E de comportamiento, nueva ejecución de 16 checks para facilitar el review, simulación presentada como llamada real, revisión por Claude Code CLI presentada como autoridad durable, ruta que dependa de `CONTINUE` sin guardar invariantes, **o nueva obligación humana por cada CODE_REVIEW ordinaria**.

## 8. Fuentes y jerarquía de contexto (documentación canónica + código inmutable)

**Documentos canónicos consultados en el mismo commit:** `docs/BUSINESS_INTENT.md`, `docs/PRODUCT.md`, `docs/CANONICAL_DECISIONS.md`, `docs/ROADMAP.md`, `docs/BACKLOG.md`, `docs/ARCHITECTURE.md`, `docs/AGENT_CONTRACTS.md`, `docs/CHANGE_DELIVERY_CONTRACT.md`, `docs/ENGINEERING_DISCIPLINE.md`, `docs/OPERATIONS.md`, `docs/backlog/MM-R01.md`. Al generar el OpenSpec, citar los enlaces de trazabilidad `business intent → capability → spec → scenario → test → evidence` y señalar divergencias históricas que no sean autoridad vigente.

**Archivos de código inspeccionados:**

- [Control plane y reanudación](https://github.com/silverberdi/mini-me/blob/5b0a8736c4efb981549f477a4e8931a96b1168ed/src/minime/services/control_plane_service.py)
- [Coordinator, freeze, current check batch y status](https://github.com/silverberdi/mini-me/blob/5b0a8736c4efb981549f477a4e8931a96b1168ed/src/minime/services/orchestration_service.py)
- [Pipeline de agente/reviewer](https://github.com/silverberdi/mini-me/blob/5b0a8736c4efb981549f477a4e8931a96b1168ed/src/minime/services/execution_pipeline.py)
- [Recovery/claims](https://github.com/silverberdi/mini-me/blob/5b0a8736c4efb981549f477a4e8931a96b1168ed/src/minime/services/recovery_convergence_service.py)
- [DeepSeek Code Review](https://github.com/silverberdi/mini-me/blob/5b0a8736c4efb981549f477a4e8931a96b1168ed/src/minime/services/deepseek_code_review_service.py)
- [Budget Service](https://github.com/silverberdi/mini-me/blob/5b0a8736c4efb981549f477a4e8931a96b1168ed/src/minime/services/budget_service.py)
- [Review Evidence](https://github.com/silverberdi/mini-me/blob/5b0a8736c4efb981549f477a4e8931a96b1168ed/src/minime/services/review_evidence.py)
- [Pruebas DeepSeek PostgreSQL](https://github.com/silverberdi/mini-me/blob/5b0a8736c4efb981549f477a4e8931a96b1168ed/tests/test_deepseek_code_review_postgres.py)
- [Pruebas Pilot Recovery PostgreSQL](https://github.com/silverberdi/mini-me/blob/5b0a8736c4efb981549f477a4e8931a96b1168ed/tests/test_pilot_checks_recovery_postgres.py)

> Nota de integridad: el código del candidato piloto `2fcad0ef…` no está publicado como commit en GitHub; este análisis mira el **control plane desplegado**, no pretende haber leído el contenido de ese worktree por SSH. Ese contenido fue reatestado por operador en el servidor. El backlog/OpenSpec sólo debe efectuar las comprobaciones focalizadas que no se pueden hacer desde GitHub.

---

# ADENDA DE VERIFICACIÓN ARQUITECTÓNICA — 20-OCT-2026

**Naturaleza:** correcciones al alcance técnico previo a OpenSpec basadas en lectura directa de GitHub `silverberdi/mini-me@5b0a8736c4efb981549f477a4e8931a96b1168ed`. Son condiciones que el workflow nativo `openspec-propose` debe incorporar en `design/specs/tasks` sin ejecutar código ni desplegar nada. No constituyen artefactos OpenSpec aprobados.

## AD-01 — Gate de autorización de checks realmente completo

La función `ControlPlaneService._execute_authorize_deepseek_code_review` (aprox. líneas 1379–1450) actualmente calcula `passing_checks` filtrando `exit_code == 0` y exige `bool(passing_checks)`. Esto **no demuestra** que el último batch para el SHA/generación tenga el conjunto exacto de checks, comandos, unicidad y ventana temporal válidos. Su validación SHALL usar la regla canónica `_validate_current_checks_batch` (o su extracción compartida), no la mera existencia de una fila con PASS. Se debe negar una autorización excepcional cuando el batch actual es parcial/fallido, incluso si existe un PASS previo. Mantener registros históricos inalterados y pruebas adversariales E02/E04.

## AD-02 — Finalización real de REVIEW_COMPLETED, no solo inferencia exitosa

`DeepSeekCodeReviewService.review_candidate` guarda veredicto, findings y consumo, pero deja la revisión como `REVIEW_RUNNING` y explica que el pipeline valida inmutabilidad post-review antes de marcar `REVIEW_COMPLETED`. `ExecutionPipeline.execute_queued_job`, aproximadamente líneas 3110+, aplica `validate_post_review_integrity`, marca `ReviewStatus.REVIEW_COMPLETED`, registra `CODE_REVIEW_COMPLETED` y puede pasar a auditoría o `READY_TO_MERGE`. La ruta frozen-review-only SHALL reutilizar o extraer **solo** finalización e integridad seguras, con fencing vigente, asentamiento de presupuesto y veredicto validado; SHALL NO invocar el pipeline completo ni sus transiciones posteriores. El resultado visible al terminar debe ser una review durable completada vinculada al candidato exacto y un Run detenido bajo gate humano, no un `REVIEW_RUNNING` eternizado ni auditoría/PR automáticos. Aceptación E01/E07/E08/E06.

## AD-03 — Contradicción de política en entradas activas de OpenSpec

`docs/CANONICAL_DECISIONS.md` y `AGENTS.md` establecen en el commit verificado que DeepSeek Direct es **revisor independiente obligatorio** para CONTRACT_REVIEW y CODE_REVIEW; OpenRouter sólo rescata trabajo de ejecución iniciado y nunca revisa. Sin embargo, `openspec/config.yaml` y `docs/CHANGE_DELIVERY_CONTRACT.md` conservan texto que describe a DeepSeek como fallback no rutinario y a OpenRouter como alternativa de revisión. En el Change se debe: (a) declarar inequívocamente la precedencia de la política de 2026-10-13 para la tarea; (b) identificar el fragmento exacto de configuración/documento contradictorio; y (c) incluir el ajuste mínimo para que el propio flujo OpenSpec y el contrato de entrega no inyecten al agente una política obsoleta durante futuras propuestas. No expandir esto a una reescritura de otros contratos. Reportar la contradicción explícitamente en proposal/design y cubrirla por anti-drift.

## AD-04 — Semántica de permiso excepcional y carrera de despacho

`_execute_authorize_deepseek_code_review` guarda `OperatorActionRecord` con identidad Run/Job/SHA/generación/manifest, cuenta/modelo, `pricing_snapshot_id`, `max_spend_usd`, `expires_at` y `action_request_id`, y rechaza autorizaciones duplicadas para el mismo candidato. `review_candidate` actualmente reserva presupuesto con un idempotency key derivado de Run/Job/SHA/manifest pero asigna `review.budget_authorization_id=None`. Antes de inferencia, el nuevo dispatch one-shot SHALL verificar, reservar/vincular y marcar duraderamente el permiso vigente una sola vez, preservando la política ordinaria de budget opcional. Riesgo de timeout/crash/claim perdido obliga a conservar `UNKNOWN/AMBIGUOUS` o equivalente sin repetir el HTTP facturable. No afirmar garantía de exactly-once de red si el proveedor no provee identidad conciliable; sí garantizar at-most-one dispatch bajo estado durable y fail-closed cuando la emisión sea incierta. E02/E06/E09.

## AD-05 — Comando nativo y frontera de planificación verificados

El repositorio contiene `.agents/skills/openspec-propose/SKILL.md` y `.agent/workflows/opsx-propose.md`, ambos con **planning boundary**: generan `proposal.md`, `design.md`, `specs/**/spec.md`, `tasks.md` y se detienen. El workflow `.agent/workflows/minime-propose-vertical.md` es wrapper fino; no reemplaza OpenSpec. El usuario autorizó avanzar a `propose`, NO `apply`. El ejecutor debe usar su comando/skill instalado en el host autorizado, detectar raíz real con `openspec context/status`, consultar `AGENTS.md` y guards, y producir la propuesta sin inferencias de revisión, operaciones de N01, suites de tests o merges.

## AD-06 — Condiciones operativas de traspaso

El commit `main` fue verificado en GitHub y coincide con la base del análisis al momento de esta adenda. La identidad de N01, su último check batch y el worktree Ubuntu son evidencia de reporte SSH anterior, no observación en vivo durante esta adenda. Ninguna DB o archivo remoto fue modificado ni se hizo `openspec propose` desde este entorno, que no cuenta con Codex/Antigravity/OpenSpec CLI. La ejecución nativa del `propose` queda como paso siguiente en un entorno de agentes autorizado.