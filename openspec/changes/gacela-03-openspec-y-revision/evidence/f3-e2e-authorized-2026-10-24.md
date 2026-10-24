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
