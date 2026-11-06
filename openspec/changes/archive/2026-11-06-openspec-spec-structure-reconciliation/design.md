## Context

See `proposal.md` for motivation and scope. The baseline validator identifies 16 main specs, but several diagnostics expose only the first structural error. The current spec text, archived changes, and Git history are the evidence sources; no product code or behavior is in scope.

## Goals / Non-Goals

**Goals:**
- Preserve each supported requirement and scenario while representing it in the canonical main-spec structure (`## Purpose`, `## Requirements`, `### Requirement:`, `#### Scenario:`).
- Trace edits to source artifacts/history and keep a record of any unresolved evidence gap.
- Prove the affected specs and global spec set validate after reconciliation.

**Non-Goals:**
- Change the meaning, strength, or applicability of product requirements.
- Repair archived `tasks.md` checkboxes, change implementations, tests, or other docs.
- Add guessed requirement text merely to satisfy the parser.

## Decisions

1. **Use the OpenSpec validator as the format authority.** For every target, first inspect the current file and exact diagnostics, then identify its source commit and related archived change. Convert legacy headings and delta sections into main-spec sections without changing requirement statements or scenarios. Alternative: hand-edit all files to the validator's surface template in one pass. Rejected because it risks hiding absent or ambiguous requirements.

2. **Derive `Purpose` only from supported content.** Summarize the existing requirements in one concise sentence. If the purpose cannot be stated without adding intent, record the evidence gap and do not invent one. Alternative: copy purpose from an unrelated historical plan. Rejected because the contract makes OpenSpec and verified repository history authoritative.

3. **Keep the change documentation-only and set `skip_specs: true`.** The work changes the format of main specs, not product behavior, so a delta spec would manufacture a behavior requirement. Alternative: create a new capability spec for “spec conformance.” Rejected because it would describe this maintenance operation as product behavior.

4. **Validate incrementally, then globally.** Run strict validation on each corrected target and `openspec validate --specs`; compare remaining errors with the recorded baseline. Do not modify unrelated specs to make the global command appear clean.

## Risks / Trade-offs

- [Risk] Legacy source or archived change may not establish the intended meaning → preserve current language and record the unresolved gap instead of expanding it.
- [Risk] Fixing a top-level section may reveal additional parser errors → iterate per target and include all observed errors in the evidence record.
- [Risk] Global validation may retain unrelated baseline failures → report them explicitly with their paths and diagnostics.

## Migration Plan

No runtime migration. Update the affected OpenSpec documents in the Issue #309 change, validate them, then use the native sync/archive workflow after merge according to the repository process.

## Evidence Record

The clean baseline was checked in a detached worktree at `8d26b89011f50953acbeef7f33b34fda2a29c2db`: 85 valid and 16 invalid specs out of 101. The table records each target's strict failure and the source revision/archive used to preserve its content.

| Main spec | Baseline strict finding | Last source revision | Archived source |
| --- | --- | --- | --- |
| `autonomous-change-orchestration` | Residual `## MODIFIED Requirements`; two requirement blocks parsed outside `## Requirements` | `a19011c` | `2026-09-17-strict-openspec-lifecycle-governance` |
| `autonomous-delivery-loop` | Missing `Purpose`; legacy `## Requirement` / `### Scenarios` headings | `64e3e08` | `2026-09-02-018.2-autonomous-end-to-end-execution` |
| `autonomous-post-merge-closure` | Missing `Purpose` and canonical main-spec structure; residual modified requirements appended below the main content | `a19011c` | `2026-09-03-018.3-autonomous-post-merge-closure`, `2026-09-17-strict-openspec-lifecycle-governance` |
| `complementary-reviewer-policy` | Residual `## MODIFIED Requirements`; modified requirement parsed outside `## Requirements` | `a19011c` | `2026-09-17-strict-openspec-lifecycle-governance` |
| `generic-provider-capacity-recovery-drain-policy` | Missing `Purpose`; scenarios were not nested under a requirement | `a472892` | `2026-09-06-generic-provider-capacity-recovery-drain` |
| `google-auth` | Missing `Purpose`; legacy `Overview` and numbered headings, with no canonical scenarios | `c4a5ccf` | `2026-09-03-019.3-google-authentication` |
| `managed-repository-runtime-isolation` | Missing `Purpose`; main spec retained delta-only `## ADDED Requirements` | `1c9b2a3` | `2026-09-28-managed-repository-runtime-isolation` |
| `openspec-lifecycle-governance` | Missing `## Requirements`; main spec retained `## ADDED Requirements` | `a19011c` | `2026-09-17-strict-openspec-lifecycle-governance` |
| `openspec-readiness` | Residual `## MODIFIED Requirements`; modified requirement parsed outside `## Requirements` | `a19011c` | `2026-08-25-009-github-app-runtime-integration`, `2026-09-17-strict-openspec-lifecycle-governance` |
| `openspec-task-tracking` | Residual `## MODIFIED Requirements`; modified requirement parsed outside `## Requirements` | `a19011c` | `2026-08-20-002-implementation-pipeline`, `2026-09-17-strict-openspec-lifecycle-governance` |
| `orchestration-driver-and-states` | Missing `Purpose`; legacy `## Requirement` / `### Scenarios` headings | `64e3e08` | `2026-09-02-018.2-autonomous-end-to-end-execution` |
| `pipeline-diagnostic-summary` | Missing `Purpose`; legacy `## Requirement` / `### Scenarios` headings | `83b59bc` | `2026-09-03-018.2-proving-diagnostic-status` |
| `pr-preparation-and-recovery` | Missing `Purpose`; legacy `## Requirement` / `### Scenarios` headings | `64e3e08` | `2026-09-02-018.2-autonomous-end-to-end-execution` |
| `provider-efficiency-and-anti-loop` | Missing `Purpose`; numbered requirement headings were not canonical | `336fece` | `2026-09-02-018.1-provider-efficiency-reviewer-independence-hardening` |
| `reviewer-independence-and-telemetry` | Missing `Purpose`; numbered requirement headings were not canonical | `336fece` | `2026-09-02-018.1-provider-efficiency-reviewer-independence-hardening` |
| `telemetry-summary` | Missing `Purpose` and `## Requirements`; main spec retained `Overview` / `## ADDED Requirements` | `1547fd6` | `2026-09-03-018.4-proving-telemetry-summary` |

The requirements and scenarios in these sources were retained or integrated into their canonical main-spec location. No unresolved intent gap was found during this structural reconciliation; any later semantic correction remains outside Issue #309.

After reconciliation, strict validation passed for all 16 targets and `openspec validate --specs` passed for all 101 specs (0 failures). The final diff is limited to those 16 main specs and the planning artifacts in this change.
