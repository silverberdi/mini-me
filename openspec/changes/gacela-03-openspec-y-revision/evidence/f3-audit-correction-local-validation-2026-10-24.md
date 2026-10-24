# F3 audit correction — local validation (2026-10-24)

## Implemented controls

- CLI and REST construct `CliAgentRunner` only from persisted F2 profiles, live CLI resolution, the capacity service, and the budget service. Missing profiles or managed bindings fail closed.
- The REST boundary passes `operator_clarification`; it no longer passes the nonexistent `operator_response` coordinator argument.
- Agent stages require exit code `0`, no timeout/preflight/environment error, and non-empty evidence. Native Propose, Apply, Verify, reviews, Sync, and Archive advance independently only after that check.
- Complexity is requested from the configured thinking agent as a structured JSON verdict with evidence. Keyword classification is not used.
- Review and Verify require one positive `ReviewVerdictPayload`; empty, textual, conflicting, or ambiguous output is rejected.
- Pytest exit code `5`, `no tests ran`, or missing collection/execution evidence is a failure.
- Git commands return typed results and raise a recoverable error on non-zero exit. PR creation, head/base identity, merge state, and Issue closure are re-read through typed GitHub adapter results before state advancement.
- FIFO continuation records the next eligible remote request only after confirmed closure; scheduler ownership is preserved.

## Verification performed

- Focused F3 contracts: `19 passed` across runner, workspace, fail-closed, native lifecycle, API boundary, and continuity tests.
- Full local regression after the classification: `781 passed, 15 skipped`.
- `python -m ruff check` on affected production and test files: PASS.
- `openspec validate gacela-03-openspec-y-revision --strict`: PASS.
- `git diff --check`: PASS.

The two former `test_e2e_isolated_fixture.py` scenarios use GitHub and agent doubles. They are explicitly skipped as non-acceptance evidence; they do not certify F3 E2E completion.

## Remote fixture observation (read-only)

The existing private fixture `silverberdi/mini-me-r01-e2e-20261014` was queried without mutation. `main` was `6c051b87eb9a8f379e9305b62773bf486a7825f5`. Issues #1, #2, #3, #4, and #5 were open. Existing PRs #2 and #4 were open and unmerged, with heads `a9f1599aa6c45eb47a0925fb0f033e01e02f33e0` and `2208e5d683e64bed79bb4110b6fca33e94e517ff`, respectively. No issue, branch, PR, merge, or fixture file was changed by this validation.

The local operator session could read the fixture. No installation-token grant for the F3 service was consumed or exposed here, and no real agent inference was started while the fixture contained unmerged historical candidates. Therefore tasks 6.3, 6.4, and the complete acceptance task remain unverified.
