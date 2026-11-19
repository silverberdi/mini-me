## 1. Apply evidence guidance

- [x] 1.1 Update the canonical `.agents/skills/minime-implementer/SKILL.md` and its provisioned `.agent/skills/minime-implementer/SKILL.md` copy to separate Apply task progress from the later immutable candidate SHA and retain candidate-specific evidence rules.
- [x] 1.2 Align the normal Apply prompt and recovery context in `orchestration_coordinator.py` with the approved worktree-diff and relevant-test evidence rule.
- [x] 1.3 Inspect existing asset/evidence checks and adjust only any check that prevents SHA-256-verified external immutable assets or intentionally untracked fixtures from supporting Apply task progress.

## 2. Regression and workflow evidence

- [x] 2.1 Add focused regression tests for normal and recovery Apply guidance, skill-copy parity, external asset wording, unsupported task completion, and candidate-specific evidence with a missing or mismatched SHA.
- [x] 2.2 Run focused tests for the prompt, recovery context, both provisioned skill paths, external asset wording, and candidate-specific SHA enforcement; focused run: 5 passed. Broader run: 78 passed, 2 failed; both failures reproduce unchanged on `origin/main` (Verify result assertion and DOC_CLOSING durable context).
- [ ] 2.3 Run a real native Apply E2E that demonstrates a completed task does not wait for the coordinator's final candidate SHA; preserve invocation, result, effects, and exact candidate identity. [DEFERRED: gather this evidence in the next production Apply after the change is deployed, per operator direction.]
