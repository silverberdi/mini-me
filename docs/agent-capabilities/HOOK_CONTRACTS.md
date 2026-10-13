# Quality Hook Contracts v1 — reutilizar PR #140

**Integración preferida:** PR [#140](https://github.com/silverberdi/mini-me/pull/140) propone CLI `minime quality-hooks`, schema `schemas/quality-hook-report.schema.json`, PRE-APPLY, POST-APPLY, VERIFY y ARCHIVE. **Su código no está fusionado** al preparar este baseline y no se asume funcional ni instalado. R01/R06 deben auditarlo y usarlo **si** pasa pruebas reales; no escribir motor duplicado.

Este documento es un contrato mínimo ya decidido para los hooks que falten/conexiones. Los motores son determinísticos donde las precondiciones son comprobables; las evaluaciones semánticas de diseño requieren revisión agent-side independiente. Un hook **no puede** autoautorizar permisos, cuota, merge ni despliegue.

## Hooks y semántica

| Hook | Trigger/entrada | Verificación obligatoria | Efecto permitido |
|---|---|---|---|
| H0 PRE-PROPOSE (nuevo, design R02) | Issue + project binding + docs/Business Intent + Rxx dossier | Repo correcto, valor real, no-goals, censo de herramientas/código existente, ausencia de contradicción canónica | PASS/BLOCKED antes de gastar IA |
| H1 PRE-APPLY (#140) | OpenSpec artifacts + scope + binding + base SHA + provider/tools | specs completas, DoR, ruta/remote/permiso, planes E2E/retirement, versión de workflow instalada, auth/capacity | PASS/BLOCKED antes de agente |
| H2 POST-APPLY (#140) | diff + candidate SHA + tasks/specs + release ledger | scope, authorship/reviewer independence, seguridad, API/DB/side effects, rastros de código viejo | PASS/FAIL/BLOCKED antes de PR |
| H3 VERIFY (#140) | resultados de checks, E2E, verificación de diseño, evidencia | matriz spec→escenario→test, regresión **tras retiro**, ausencia de CRITICAL/HIGH sin resolver | PASS/FAIL/BLOCKED |
| H4 ARCHIVE (#140) | merge evidence + native OpenSpec sync/archive + deployment/closure | no auto-merge, candidate identidad, DoD, postdeploy real, Git protegido, ledger cerrado | PASS/BLOCKED antes DONE |

**Plan de incorporación:** R01 exige gates mínimos H1–H3 solo donde existan y sean verificables; R02 cubre H0; R04 integra H4; R06 prueba uso selectivo y E2E de todos. PR #140 no debe ser fusionado mecánicamente sin revisar drift ni cambios de CLI.

## Contrato de entrada (conceptual — implementar dentro de R01/R06)

```json
{
  "contract_version": "1.0",
  "hook_id": "PRE_APPLY",
  "change_slug": "real-openspec-agent-execution",
  "project_id": "project-from-durable-binding",
  "run_id": "durable-run",
  "job_id": "durable-job",
  "repository": {
    "remote": "validated-remote",
    "managed_root": "assigned-worktree",
    "base_sha": "commit-sha",
    "candidate_sha": null
  },
  "openspec": {
    "schema": "spec-driven",
    "active_change": "real-openspec-agent-execution",
    "tool_version": "observed-version",
    "native_workflow": "observed-installed-name"
  },
  "spec_ids": ["R01-S01"],
  "e2e_ids": ["R01-E01"],
  "evidence_refs": ["immutable-or-redacted-reference"],
  "retirement_ledger_ref": "none-or-versioned-reference",
  "policy_snapshot_ref": "durable-policy-reference"
}
```

El runtime rellena datos desde DB/config/Git/OpenSpec/CLI, NO desde texto del agente; no usar placeholders como autoridad. Los hashes, fechas y permisos deben ser verificables.

## Contrato de salida (orientativo, adaptar a schema real del PR #140)

```json
{
  "contract_version": "1.0",
  "hook_id": "PRE_APPLY",
  "verdict": "BLOCKED",
  "finding_ids": ["MISSING_REAL_E2E_PLAN"],
  "blocking_reasons": ["No E2E en entorno real para el workflow apply"],
  "evidence_refs": ["path-or-event-id"],
  "candidate_sha": null
}
```

- `PASS` solo con evidencia positiva suficiente; `FAIL` para incumplimiento, `BLOCKED` para ausencia de prueba/precondición. `UNKNOWN` nunca se transforma en PASS.
- Secretos y tokens deben redactarse. No ejecutar un side effect externo dentro de hooks de solo lectura.
- Idempotencia: mismo snapshot/inputs produce mismo veredicto; una evidencia nueva obliga a invalidar reporte antiguo.
- La evaluación de arquitectura/manual no puede esconderse tras `PASS` programático: registrar `MANUAL_REVIEW_REQUIRED` con motivo cuando el hook no pueda decidir.
- Cada hook necesita unit+integration, E2E de denegación, falso positivo/negativo representativo, compatibilidad Codex y Antigravity, y una ejecución real de producto antes de habilitarlo como gate.

## Invariantes adversariales de hook

1. `proposal.md` escrita por plantilla Python pero sin agente `propose` → BLOCKED.
2. Nombre de skill existe pero agent trace no prueba uso → NO_VERIFIED.
3. PR generado sin reviewer distinto del autor sustancial → BLOCKED.
4. Código viejo aún alcanzable sin RETAIN-WITH-REASON aprobado → BLOCKED.
5. Tests/health PASS antes del retiro pero fallos E2E después → FAIL.
6. Corrector intenta reducir specs, reetiquetar evidencia o bajar política para pasar gate → BLOCKED + revisión humana.
7. Hook solicitado con payload de otro repo/candidate SHA → BLOCKED antes de inferencia.
