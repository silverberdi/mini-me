## 1. Establish evidence for each target

- [x] 1.1 Record the strict validator diagnostic, latest source commit, and relevant archived change (when available) for all 16 specs named in Issue #309.
- [x] 1.2 For every target, map the current requirement/scenario text to its evidence source and record any intent that cannot be established without inference.

## 2. Reconcile modified main specs

- [x] 2.1 Integrate the appended modified requirements into the existing requirements in `autonomous-change-orchestration`, `complementary-reviewer-policy`, `openspec-readiness`, and `openspec-task-tracking`; remove delta-only headers from these main specs while preserving supported requirements and scenarios.
- [x] 2.2 Strict-validate those four specs and confirm the previously invisible requirements are parsed as part of `## Requirements`.

## 3. Normalize legacy main-spec structure

- [x] 3.1 Add evidence-backed `Purpose` and canonical requirement/scenario structure to `autonomous-delivery-loop`, `autonomous-post-merge-closure`, `orchestration-driver-and-states`, `pipeline-diagnostic-summary`, and `pr-preparation-and-recovery` without changing requirement meaning.
- [x] 3.2 Add evidence-backed `Purpose` and canonical requirement/scenario structure to `generic-provider-capacity-recovery-drain-policy`, `google-auth`, `provider-efficiency-and-anti-loop`, `reviewer-independence-and-telemetry`, and `telemetry-summary`.
- [x] 3.3 Reconcile `managed-repository-runtime-isolation` and `openspec-lifecycle-governance` as main specs, replacing delta-only top-level sections with canonical main-spec sections while preserving their supported requirements and scenarios.
- [x] 3.4 Strict-validate all 12 specs in this section and document any unresolved intent gap instead of adding inferred content.

## 4. Validate the reconciliation

- [x] 4.1 Run strict validation on all 16 target specs and confirm each passes.
- [x] 4.2 Run `openspec validate --specs`, compare with the recorded baseline, and document any remaining repository-wide failures outside this Issue's 16 targets.
- [x] 4.3 Confirm the final diff contains only the 16 target files under `openspec/specs/` and this Change's planning artifacts; no source code, tests, or runtime files are changed.
