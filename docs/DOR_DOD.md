# Definition of Ready and Done

## Definition of Ready
A change may enter READY only when code-verifiable checks confirm:
- registered project and immutable `project_id`;
- valid repository identity/access;
- GitHub Issue in that repository;
- valid binding to exactly one OpenSpec change;
- explicit value/purpose;
- observable acceptance criteria;
- no unresolved ambiguity that materially changes behavior, architecture, scope, security or cost;
- dependencies identified;
- base branch defined;
- implementer + complementary reviewer configured;
- deterministic project checks configured;
- provider/privacy/fallback policy configured;
- roadmap/stage allows the work now;
- OpenSpec artifacts valid;
- repository/workspace preflight passes;
- required primary capacity exists to start;
- for UI changes requiring human validation: scenarios and a valid preview deployment contract exist.

DeepSeek/OpenRouter/Qwen availability at that instant does not by itself block READY unless a project policy explicitly requires it before starting.

## Definition of Done
DONE requires all applicable conditions:
- implementation complete;
- final deterministic checks pass;
- complementary authoritative review complete;
- correction loop resolved;
- DeepSeek Direct audit complete and recorded;
- required UI human validation completed on the bound candidate, or human evidence review completed for non-UI changes;
- blocking findings resolved or explicitly overridden by authorized human decision with reason;
- human approval recorded;
- candidate pushed and PR exists;
- human merge confirmed;
- production deployment completed when required;
- production verification passed;
- OpenSpec synchronized/archived;
- GitHub Issue/Project synchronized and closed/done;
- final metrics/evidence persisted;
- temporary worktree cleaned;
- no pending post-merge operation remains.

`APPROVED != DONE`, `MERGED != DONE`, `DEPLOYED != DONE`.

## Reopen rule
A defect found after DONE creates a new related Issue/OpenSpec change; do not resurrect a completed execution job and corrupt historical metrics.
