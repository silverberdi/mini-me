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
- engineering inventory of existing capabilities and explicit reuse/replace/retire decisions using `docs/ENGINEERING_DISCIPLINE.md`;
- seeded agent skills/hooks/harness contracts inventoried; compatibilities/changes recorded rather than reinvented;
- base branch defined;
- implementer + complementary reviewer configured;
- deterministic project checks configured and a testable **E2E scenario for the promised value** plus postdeploy proof plan linked to specs;
- provider/privacy/fallback policy configured;
- roadmap/stage allows the work now;
- OpenSpec artifacts produced or revised by the authorized **agent-side** OpenSpec workflow and structurally valid; if the change is still at intake/propose, DoR applies to the next safe stage, not a fabricated READY implementation;
- repository/workspace preflight passes;
- actual stage preflight for admission verifies provider authentication, compatible installed native OpenSpec workflow and a safe bounded capacity window; if provider is unavailable or quota unknown, backlog can remain prepared but dispatch MUST wait;
- for UI changes requiring human validation: scenarios and a valid preview deployment contract exist.

DeepSeek/OpenRouter/Qwen availability at that instant does not by itself block READY unless a project policy explicitly requires it before starting.

## Definition of Done
DONE requires all applicable conditions:
- implementation complete;
- final deterministic checks pass;
- real stage-level E2E and end-to-end delivery tests pass using real agent/CLI, OpenSpec, Git and GitHub as required; no fake-runner evidence is accepted as a product gate;
- complementary authoritative review complete;
- correction loop resolved;
- optional authorized independent fallback audit complete **only when** a policy/human decision explicitly requires it; routine mandatory quality gate is distinct primary-agent independent review;
- required UI human validation completed on the bound candidate, or human evidence review completed for non-UI changes;
- blocking findings resolved or explicitly overridden by authorized human decision with reason;
- human approval recorded;
- candidate pushed and PR exists;
- human merge confirmed;
- production deployment completed when required;
- production verification passed **at the changed functionality level** (not only HTTP health), with evidence bound to deployed SHA/digest, or explicitly marked awaiting deployment before DONE;
- OpenSpec synchronized/archived using supported native workflows with diff/semantic checks, respecting protected Git branches and human merge authority;
- GitHub Issue/Project synchronized and closed/done;
- final metrics/evidence persisted, including agent identity/model, actual OpenSpec workflows invoked, skill/hook versions, candidate/PR, stage E2E, postdeploy E2E and authorized cost;
- temporary worktree cleaned;
- no pending post-merge operation remains.

`APPROVED != DONE`, `MERGED != DONE`, `DEPLOYED != DONE`.

## Reopen rule
A defect found after DONE creates a new related Issue/OpenSpec change; do not resurrect a completed execution job and corrupt historical metrics.
