# mini me — Agent Capability Pack v1 (baseline canónica)

**Objetivo:** los agentes NO deben inferir desde cero los skills/hooks/commands/guards/harnesses de mini me. Este paquete es **material inicial versionado**, listo para recibir ajustes puntuales mediante `propose/update/apply/verify` de OpenSpec. No modifica los workflows oficiales OpenSpec, no crea un segundo lenguaje de scripts y no habilita inferencia por sí solo.

## Inventario y estado honesto

| Artefacto | Ubicación inicial | Estado en PR #153 | Responsable y uso |
|---|---|---|---|
| OpenSpec workflows oficiales | `.agent/workflows/opsx-*.md`, `.agents/skills/openspec-*/SKILL.md` | **EXISTING** en repo; no duplicados | Agente ejecuta propose/update/continue/apply/verify/sync/archive de forma compatible con la instalación |
| Canonical context, scope y repository-binding guards | `.agent/skills/minime-*-guard/SKILL.md` y mirrors | **EXISTING**, orientativos, no representan bloqueo técnico ejecutable | Antes de cualquier modificación y antes de PR |
| Engineering discipline skill | `.agent/skills/minime-engineering-discipline/SKILL.md` y mirror | **SEEDED V1**, usable como instrucción por agentes | Propose, apply, verify, review |
| Safe retirement skill | `.agent/skills/minime-safe-retirement/SKILL.md` y mirror | **SEEDED V1** | Apply y verify cuando hay sustitución |
| Real E2E proof skill | `.agent/skills/minime-real-e2e-proof/SKILL.md` y mirror | **SEEDED V1** | Design, apply, verify y release |
| Wrappers de comandos de etapa | `.agent/workflows/minime-propose-vertical.md`, `minime-apply-vertical.md`, `minime-verify-vertical.md` | **SEEDED V1**; ayudas de invocación, NO ejecución automática | Agente sigue un workflow OpenSpec real |
| Quality hooks determinísticos | PR [#140](https://github.com/silverberdi/mini-me/pull/140) propone motor y CLI | **PENDING REVIEW**, no presente en main; no lo reimplementar | Agente integra en R01/R06 tras auditoría y pruebas |
| Hook contract | [HOOK_CONTRACTS.md](HOOK_CONTRACTS.md) | **SPECIFIED V1**, no ejecutable | Contrato técnico para configurar/integrar el motor de #140 |
| Provider stage harness | [HARNESS_CONTRACT.md](HARNESS_CONTRACT.md) | **SPECIFIED V1**, no está conectado aún al daemon | R01 ejecuta primer adapter real, R06 amplía selección |
| Retirement baseline | [RETIREMENT_MAP.md](RETIREMENT_MAP.md) | **SPECIFIED V1**, candidatos a inspeccionar, no autorización para borrado | R01–R10 |

**Estados permitidos para reportar:** EXISTING, SEEDED/ADVISORY, SPECIFIED/NOT_WIRED, VERIFIED_LIVE, RETIRED. No confundir `SKILL.md` existente con hook ejecutable ni un schema con E2E probado.

## Capacidades mínimas por etapa

| Stage | Skill / guard / hook baseline | Workflow del agente | Salida verificable |
|---|---|---|---|
| INTAKE / PROPOSE | canonical context + engineering discipline + scope guard + Rxx dossier; hook PRE-PROPOSE | `openspec-propose` o `opsx-propose` instalado | proposal/design/specs/tasks + matriz intent/espec/test |
| UPDATE / CONTINUE | mismas reglas + ownership + registro de divergencia; PRE-PROPOSE recheck | `openspec-continue*` / `opsx-continue` cuando exista | artifacts revisados y DoR |
| PRE-APPLY | binding guard + capabilities/preflight + hook PRE-APPLY | `openspec-apply-change` / `opsx-apply` | permiso, root seguro, cuota y snapshot candidatos |
| APPLY | engineering discipline + safe-retirement (si sustituye) + scope/binding guards | agent-side apply | código real, tasks + SHA + diff + ledger |
| VERIFY | real-e2e + engineering + hook VERIFY | `opsx-verify` / skill verify instalado | checks + E2E por stage y valor + veredicto |
| INDEPENDENT REVIEW | `minime-reviewer` + engineering + safe retirement + hook POST-APPLY | revisión read-only del **otro** agente; OpenSpec artifact as source | findings, exact candidate SHA, NO same-author review |
| PR / HUMAN | binding, candidate identity + evidence check | GitHub PR vía orquestación, nunca auto-merge | PR, human gate, UI validation cuando aplica |
| MERGE / CLOSURE | hook ARCHIVE, native sync/archive, rollback | workflows OpenSpec instalados | specs correctas, merged SHA, deployment E2E, DONE no ficticio |

**Nombres de comandos:** no inventar `opsx` como binario. El nombre real se resuelve desde `./.agent/workflows/`, `./.agents/skills/` y `openspec status/instructions`; en este repo está `openspec-apply-change` para Codex. Si una etapa/workflow no está instalado, el preflight bloquea y recomienda instalación legítima; no reemplaza por un prompt de programación libre.

## Modo de uso antes de conectar al runtime

1. Leer docs canónicos, la ficha MM-Rxx, este manifest, los contratos de hooks/harness y el Removal Map.
2. Verificar el censo real de archivos/versions del repo y PR #140. Si cambió, actualizar por OpenSpec; no suponer que existe.
3. Ejecutar workflow agente conforme a OpenSpec; usar los skills seed como directivas de trabajo, no como máquina de ejecución.
4. La implementación de hooks/harness y su cableado ocurren **dentro del Change vertical que los necesita**, con E2E real y política de gasto. No bloquear R01 esperando toda R06/R09.
5. En cada reemplazo, hacer Removal Ledger y desmontar en el mismo Change después de paridad real. Proteger historial y side effects.

## Conflictos por resolver en diseño del Change, no adivinar

- PR #140 agrega hooks PRE-APPLY/POST-APPLY/VERIFY/ARCHIVE pero no PRE-PROPOSE. Cubrir PRE-PROPOSE con guard de contexto/admisión en R02 o integración aprobada; no fingir que PR #140 ya lo ejecuta.
- La skill oficial `openspec-propose` tiene **planning boundary**: detener tras propuesta y esperar nueva instrucción. Mini me debe emitir un **nuevo dispatch autorizado en otra etapa** tras gate, no cambiar la skill o encadenar apply en el mismo prompt.
- Los contratos `HARNESS_CONTRACT.md` y `HOOK_CONTRACTS.md` son diseños v1 completos para implementación, **no scripts activos ni verificación de seguridad demostrada**.
- El runner local Qwen con patch applier existe, pero NO prueba que sea un agente con herramientas OpenSpec. No declararlo alternativa equivalente ni borrarlo por error; revisar usos reales antes de retiro.
