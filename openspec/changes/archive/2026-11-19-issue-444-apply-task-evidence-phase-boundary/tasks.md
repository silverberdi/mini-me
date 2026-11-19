## 1. Apply evidence guidance

- [x] 1.1 Update the canonical `.agents/skills/minime-implementer/SKILL.md` and its provisioned `.agent/skills/minime-implementer/SKILL.md` copy to separate Apply task progress from the later immutable candidate SHA and retain candidate-specific evidence rules.
- [x] 1.2 Align the normal Apply prompt and recovery context in `orchestration_coordinator.py` with the approved worktree-diff and relevant-test evidence rule.
- [x] 1.3 Inspect existing asset/evidence checks and adjust only any check that prevents SHA-256-verified external immutable assets or intentionally untracked fixtures from supporting Apply task progress.

## 2. Regression and workflow evidence

- [x] 2.1 Add focused regression tests for normal and recovery Apply guidance, skill-copy parity, external asset wording, unsupported task completion, and candidate-specific evidence with a missing or mismatched SHA.
- [x] 2.2 Run focused tests for the prompt, recovery context, both provisioned skill paths, external asset wording, and candidate-specific SHA enforcement; focused run: 5 passed. Broader run: 78 passed, 2 failed; both failures reproduce unchanged on `origin/main` (Verify result assertion and DOC_CLOSING durable context).
- [x] 2.3 Run a real native Apply E2E that demonstrates a completed task does not wait for the coordinator's final candidate SHA; preserve invocation, result, effects, and exact candidate identity. **Evidence:** deployed Mini Me Run `014c21dd-1f5f-4b25-a3df-77eace9e18c7` for Boxio Issue #21 executed native Apply in the owned worktree; Apply attempts `e4d1dc31-f7f3-4a1a-a13e-49a7ee3e9a2e` and recovery `6a4e6951-312f-43b8-acbe-0adf7ba8bd66` completed all 22 tasks before Verify; native Verify `ae17ba53-1d8b-4d82-85bd-ceb01f76daa9` passed on candidate SHA `e07470ce836fbbded64a9a0fd7dc393ad251312b` (PR [#24](https://github.com/silverberdi/multiplo/pull/24), merged as `18d5c97e7f93327f78dc626545f0acf6907e1e0c`).
