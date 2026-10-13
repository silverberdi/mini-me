# Product Definition

## Core user
One technical owner/operator supervising several software repositories.

## Primary outcomes
1. Centralize pending work and visible progress in one personal GitHub Project.
2. Convert a READY OpenSpec change into code using the **real agent-side OpenSpec workflows** without manual handoffs; also let authorized GitHub Issues generate agent-led OpenSpec proposals.
3. Use Codex ↔ Antigravity as stage-assigned proposer/implementer/reviewer, with candidate-author/reviewer independence.
4. Verify changes through native OpenSpec agent workflows, deterministic checks, independent primary-agent review and real end-to-end tests; DeepSeek is not a mandatory routine auditor.
5. Survive daemon restart, provider exhaustion and transient failures without losing useful work.
6. Use DeepSeek/OpenRouter only as compatible explicitly authorized and budgeted fallbacks after both subscription primaries are unable to complete a required stage; never admit fresh work merely because paid fallback is available.
7. For UI changes requiring human validation, deliver a testable containerized preview plus exact instructions for what to test and expected results.
8. Automate draft PR, **native OpenSpec sync/archive**, authorized deployment and closure around human approval/merge gates; mini me does not implement OpenSpec or write code itself.
9. Measure value delivered and verified postdeployment (not test counts), real E2E, quality, provider effectiveness, autonomy, interrupted-work recovery and authorized fallback cost.
10. Progressively support self-development: mini me may select and orchestrate changes to its own repo but never auto-merge or bypass policy.

## MVP non-goals
- Autonomous merge.
- Autonomous product/architecture decisions when specs are ambiguous.
- Reimplementing OpenSpec proposals, apply, verify, sync or archive as deterministic Python or prompts divorced from agent workflows.
- Claiming product delivery based only on unit/integration tests, fake agent runners or HTTP health checks.
- Dynamic learned provider routing.
- Multiple simultaneous implementation changes in one repository.
- Distributed remote workers.
- Commercial multi-installation support or multitenancy.
- PWA remote supervision (post-MVP).
- Qwen local holding any correctness/security/human authority.
- OpenRouter starting new work merely because budget is available.

## First adoption sequence
1. Deliver a real agent-side OpenSpec implementation, independent review and PR (MM-R01) while preserving existing state/N01.
2. Prove GitHub-to-OpenSpec intake, queue and real postmerge closure (MM-R02–R04), with quota-safe recovery (MM-R05).
3. Add necessary skills/hooks/harnesses and operational UI (MM-R06–R07), then prove on a second authorized repository (MM-R08).
4. Enable governed capability evolution and self-development only after real E2E evidence (MM-R09–R10).
