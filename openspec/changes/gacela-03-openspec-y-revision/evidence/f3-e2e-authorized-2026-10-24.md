# F3 authorized E2E evidence — 2026-10-24

## Scope and authorization

The authorized fixture is `silverberdi/mini-me-r01-e2e-20261014`. The authorization
comment is PR #180 comment `6388799679`; it permits the Issue #5 run, the Issue #6
run with a separate `Estoy enterado` gate before its first merge, and FIFO
continuation evidence for Issue #7. It does not authorize production writes,
scheduler activation, fallback providers, or merging PR #180.

The isolated runtime used service identity `minime`, the GitHub App installation
`154974444`, a disposable PostgreSQL database, and the fixture's managed
worktree root. Historical PRs #2 and #4 and disabled Issues #1 and #3 were
preserved.

## Preflight

- OpenSpec 1.13.1 was initialized through its official CLI with `delivery=both`
  and all twelve configured workflows. The generated `.agents/skills` and
  `.agents/workflows` trees were produced by the CLI; no equivalent files were
  written manually.
- GitHub App installation access was observed through the service adapter with
  effective Issues, Contents, and Pull Requests write grants. No operator PAT
  or `gh` session was used by the runtime.
- `codex login status` and `agy models` succeeded under `minime`; the configured
  Codex and Antigravity model identities were not substituted.
- The disposable database was migrated to Alembic head. Capacity observations
  for Codex and Antigravity were acquired only through the read-only provider
  capacity path and recorded as available/success. OpenRouter fallback remains
  disabled with an explicit disabled policy and zero caps.

## Authorized Issue #5 attempt

The first invocation selected Issue #5 by FIFO and created the isolated
worktree. The coordinator run was:

`7d227da6-19be-4f7d-8bd9-f398bafcdc2e`

The run reached `VALIDATING` and returned `PAUSED` with the message:

`Thinking agent did not return a positive structured complexity verdict.`

The agent invocation was real and produced native OpenSpec proposal artifacts in
the preserved worktree, but no positive structured verdict was returned. No
candidate SHA, PR1, PR2, merge, or Issue closure was produced. The model call
was not repeated because its consumption was already authorized and ambiguous
continuation would violate the zero-retry rule.

The preserved worktree is the coordinator-owned request-5 worktree. The fixture
remote `main` and historical PRs were not modified by this attempt.

## Deterministic validation

- Focused runner/confinement regression: `7 passed`.
- Full isolated regression: `784 passed, 12 skipped, 4 failed`.
- The four failures were classified as environment/pre-existing compatibility
  observations: two process-group cleanup assertions under the host's Python
  3.14.4 process semantics, one assertion expecting a legacy `/minime/pycache/`
  prefix while the implementation uses an isolated temporary prefix, and one
  DeepSeek stage-profile assertion that passed when isolated. No F3 E2E result
  was promoted from these failures.
- OpenSpec strict validation and `git diff --check` pass for this Change.

## Acceptance state

Tasks 5.8, 6.3, 6.4, and 6.5 remain incomplete. The E2E is `BLOCKED` at the
first authorized scenario because the real thinker did not return the required
positive structured complexity verdict. Issue #6 was not mutated, no PR1 was
created, no human merge gate was reached, and Issue #7 was not started.

## Recovery audit for run `7d227da6-19be-4f7d-8bd9-f398bafcdc2e`

A read-only inspection of the disposable PostgreSQL database found:

- one active run with the original run ID, `current_stage=VALIDATING`,
  `resumable_stage=VALIDATING`, no active job, no candidate, and no second run;
- no persisted job attempt, job log, evidence diagnostic, stage event, or external
  action for the complexity call;
- the previous `stop_details.complexity=moderate` was the run-construction
  default, not a verified classification result, and is no longer treated as
  evidence by the coordinator;
- the preserved request worktree still contains `proposal.md`, `design.md`,
  `tasks.md`, and the OpenSpec spec, and strict OpenSpec validation passes.

The original process output, exit code, timeout, and transport metadata were not
durably recorded. Therefore the original failure cannot be proven to be an agent
failure, transport failure, incomplete response, or parser failure; it is
specifically **irrecoverable as a classified cause** from the available evidence.
No new model invocation was made to fill that gap.

The coordinator correction now preserves the worktree and run identity, resumes
`VALIDATING` without re-running Propose when the existing artifacts pass strict
validation, blocks any failed Explore result, and persists a typed, redacted
complexity assessment (`VALID`, `EXECUTION_FAILED`, `PREFLIGHT_FAILED`,
`INVALID_OUTPUT`, or `MISSING_EVIDENCE`) before allowing progression.

Deterministic regression after the correction: `15 passed`; affected Ruff:
`PASS`; OpenSpec strict and `git diff --check`: `PASS`. No agent or model was
invoked by these tests. The complete isolated regression reached `788 passed,
12 skipped` with the same four pre-existing Python 3.14/cache/profile
compatibility failures classified above, plus no F3-specific failure after the
fail-closed expectation updates.

## Bounded classification checkpoint — 2026-10-24

The checkpoint was published at commit `3ea4797b6c4dc3879675b8b7d18e69991ea05f1e`
and executed only against the preserved run above. The first environment check
correctly stopped before invocation when the service environment pointed at
`minime`; the isolated runtime was then bound to the disposable database
`minime_f3_e2e_20261024`, whose Alembic revision is
`f2_retire_project_legacy_context`. No production database was written.

Final preflight evidence: exactly one run, active `VALIDATING`, strict OpenSpec
validation PASS, original worktree and four proposal artifacts present, Issue
`#5` read through the GitHub App, App permissions verified for Issues/Contents/
Pull Requests, Codex and Antigravity profiles available, confinement preflight
PASS, and fallback disabled. The original issue title and body were passed to
the checkpoint; artifact hashes were recorded with the result.

Exactly one Codex invocation was made for the existing run:

- attempt: `6519f82c-c023-4e3f-8291-490274bfe88e`
- model: `gpt-5.6-luna`; effort: `medium`; provider: Codex
- exit code: `0`; timeout: `false`; preflight error: none
- result: `INVALID_OUTPUT`; no complexity verdict was accepted
- reason: the output contained the JSON object followed by additional Codex
  session/inspection output, so it was not exactly one structured JSON object
- consumption: `unknown`; no retry was made
- persisted artifact hashes: `proposal.md`, `design.md`, `tasks.md`, and the
  sanitized-filename spec remain associated with the attempt

The run remains `VALIDATING`, active, with one run and no candidate, job, Apply,
review, PR, merge, or Issue mutation. Explore and Propose were not repeated;
Apply and independent review were not invoked. The checkpoint persists an
`IN_PROGRESS` record before dispatch and the final typed diagnostic afterward,
then stops before Review/Apply as required.

## Deterministic recovery audit — 2026-10-24

The disposable PostgreSQL read-only inspection of attempt
`6519f82c-c023-4e3f-8291-490274bfe88e` found `attempt_count=2` (the durable
`IN_PROGRESS` marker and its final record), `exit_code=0`, `timed_out=false`,
`consumption=unknown`, four artifact hashes, and a 4,000-character combined
output. The persisted record has no separate `structured_output` or
`diagnostic_output` channel and no non-truncation proof. It therefore cannot
demonstrate one authentic final JSON message separated from Codex transport
and logs. The classification remains `INVALID_OUTPUT`; no verdict was
recovered or fabricated.

The Run remains unique, active, and `VALIDATING`, with no active job and no
candidate. No provider was called during this audit.

The published correction separates future stdout response data from stderr
diagnostics, records truncation explicitly, persists issue/Run context hashes
alongside artifact hashes, and rejects reuse when any hash differs. Re-entry
from `INVALID_OUTPUT` or `IN_PROGRESS` now returns `BLOCKED`/`PAUSED` without
dispatching a provider; only an explicitly authorized new invocation could
change that state. Recovery accepts only a complete, non-truncated, single
JSON response with attempt metadata, artifact hashes, and context hashes.

Deterministic tests cover separated diagnostics, contradictory responses,
incidental JSON, truncation, hash changes, explicit-channel recovery, and
zero provider calls on invalid re-entry. F3 remains 37/41; tasks 5.8, 6.3,
6.4, and 6.5 remain incomplete.
