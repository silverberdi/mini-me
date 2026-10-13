# Provider–OpenSpec Stage Harness v1

**No confundir:** este contrato describe el harness que mini me orquestará; no reemplaza las skills oficiales OpenSpec ni constituye un runner conectado hasta que el Change correspondiente lo pruebe. El agente con herramientas desarrolla, prueba y revisa; mini me ejecuta despacho, seguridad, cuota, aislamiento y evidencia.

## Request mínimo, versionado

```json
{
  "version": "1.0",
  "project_id": "durable-id",
  "change_slug": "real-openspec-agent-execution",
  "run_id": "same-durable-run",
  "job_id": "same-durable-job",
  "generation": 1,
  "stage": "APPLY",
  "provider": "codex",
  "provider_account_ref": "secret-store-reference",
  "role": "implementer",
  "worktree": {
    "root": "validated-owned-worktree",
    "remote": "validated-remote",
    "base_sha": "observed-commit",
    "head_sha": "observed-commit"
  },
  "workflow": {
    "kind": "native-agent-skill",
    "installed_name": "openspec-apply-change",
    "tool_version": "observed-version",
    "config_ref": "openspec/config.yaml"
  },
  "required_skills": [
    "minime-engineering-discipline",
    "minime-safe-retirement",
    "minime-real-e2e-proof"
  ],
  "guard_refs": ["canonical-context", "repository-binding", "scope-roadmap"],
  "policy_snapshot_ref": "authorized-stage-policy",
  "stage_budget_ref": "authorized-budget-or-no-spend",
  "traceability_ref": "docs/backlog/MM-R01.md",
  "idempotency_key": "durable-unique-key"
}
```

**No construyas prompts gigantes:** el envoltorio contiene instrucción mínima: seleccionar cambio/etapa en skill OpenSpec instalado, leer referencia canónica/dossier y cumplir gates. Nunca afirmar que `openspec validate` invocó el razonamiento del agente. **No permitir CLI de proveedor sin tool-use comprobable para APPLY.**

## Result/telemetry mínimo

```json
{
  "version": "1.0",
  "run_id": "same-durable-run",
  "job_id": "same-durable-job",
  "stage": "APPLY",
  "attempt_id": "durable-attempt",
  "provider": "codex",
  "model_identity": "observed-provider-model",
  "agent_workflow": "openspec-apply-change",
  "workflow_observed": true,
  "result": "COMPLETED",
  "candidate_sha": "observed-commit",
  "produced_artifacts": ["observed-relative-path"],
  "check_refs": ["immutable-check-result"],
  "e2e_refs": ["evidence-after-retirement"],
  "reviewer_model_identity": null,
  "retirement_ledger_ref": "docs-or-evidence-path",
  "capacity_signal_ref": "observed-signal-or-unknown",
  "cost_evidence_ref": "observed-or-estimated-with-confidence"
}
```

`result`: `COMPLETED|WAITING_CAPACITY|AUTH_REQUIRED|BLOCKED|FAILED|UNKNOWN` (el modelo de dominio canon puede mapear estos nombres, nunca alterar invariantes). `workflow_observed` no es afirmación textual del modelo: requiere rastro de la herramienta y artefactos/diff en el workspace.

## Etapas mapeadas a workflows instalados

| Stage | Adaptador real | Workflow | Guard / rollback |
|---|---|---|---|
| PROPOSE | Codex/AGY CLI con herramientas | `openspec-propose` / `opsx-propose` | solo planning; **retorno al humano/política** antes de nuevo APPLY dispatch |
| UPDATE | Agente seleccionado | `openspec-continue-change`/update instalado | versionar artifact diffs, revalidar DoR |
| APPLY | Agente implementer | `openspec-apply-change` / `opsx-apply` | root/secret/capacity/idempotency guards |
| VERIFY | Agente verificador | `openspec-verify-change`/ `opsx-verify` instalado | checks + E2E + release gate |
| REVIEW | **otro agente/modelo** | revisión read-only según `minime-reviewer` | NO self-review |
| SYNC / ARCHIVE | agente/OpenSpec | `openspec-sync-specs`/ `opsx-sync`; `openspec-archive-change`/`opsx-archive` | merge authority, protected Git, native correctness |
| CLOSURE | daemon | GitHub/DB/deployment deterministic steps | saga/idempotency and postdeploy E2E |

**Los nombres son ejemplos del repo observado, no garantías de compatibilidad**: preflight resuelve nombres reales, tool versions y schema; no hackear OpenSpec.

## Checkpoints y fallos

- Antes de llamar IA: validar binding, remote/WT ownership, version de CLI, skill instalado, policy snapshot, quota/auth con fuente/confianza, checkpoint y side effect state. Si falla, **no inference**.
- Side effect `UNKNOWN`: observar y reconciliar, no repetir.
- Cuota/auth: preservar mismo run/job/WT/attempt history y esperar; no reintentos compulsivos, no fallback pagado sin aprobación.
- Tras resultado: validar artifact/source diff y que el agente *realmente ejecutó* el workflow; ledger de retiro y checks tras eliminación; reviewer distinto y PR humano.
- Runtime no consume estas interfaces hasta que R01/R06 las implementen y E2E las acrediten.
