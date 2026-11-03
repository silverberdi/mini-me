## 1. Convergent code-review prompt

- [x] 1.1 Update `_run_code_review` to include the complete candidate diff and apply substantive scope plus BLOCKER/MAJOR/MINOR convergence guidance.
- [x] 1.2 Preserve the existing reviewer invocation, identity, verdict schema, parsing, and stage routing.

## 2. Focused verification

- [x] 2.1 Add focused tests proving a diff longer than 4,000 characters reaches the reviewer in full and the prompt includes severity and convergence instructions.
- [x] 2.2 Run focused code-review tests and strict OpenSpec validation; record the exact commands and outcomes.
  - Evidence: `/Users/silveriobernal/Documents/Code/Development/mini-me/.venv/bin/pytest tests/test_f5_agent_result_integrity.py -q` — 18 passed; `openspec validate code-review-convergence --strict` — valid; `/Users/silveriobernal/Documents/Code/Development/mini-me/.venv/bin/ruff check src/minime/services/orchestration_coordinator.py tests/test_f5_agent_result_integrity.py` — passed; `git diff --check` — passed.
