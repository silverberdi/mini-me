## Context

See `proposal.md` for motivation and `specs/` for observable behavior. The current implementation has the publication-claim regex in `orchestration_coordinator.py`; candidate browser discovery in `candidate_test_resolver.py` checks an environment override and then home-directory caches; worktree Git checks already use `--exclude-standard`, which honors `.git/info/exclude`. Proposal executability is assessed by `ProposalFeasibilityEvaluator`, whose report and current persisted assessment are existing authorities.

Constraints: no changes to production deployment responsibility, no new service or database table, and no weakening of the canonical rule that real integration criteria need observable invocation, result, and effects.

## Goals / Non-Goals

**Goals:** make candidate acceptance depend on observable repository/test evidence instead of static publication wording; locally ignore only standard generated cache paths; resolve Playwright browsers from the isolated runtime installation; and recognize evidence-backed, functionally sufficient local contingencies during proposal feasibility.

**Non-Goals:** implement deployment/publishing, download browsers at runtime, ignore arbitrary untracked files, or treat prose/LLM assertion alone as proof of an external integration.

## Decisions

1. **Remove the publication text gate, retain ordinary candidate evidence checks.** Delete `_PUBLISHED_CANDIDATE_CLAIM` and its call-site rejection, then remove any helper/marker logic that becomes unreachable after checking all callers. Git candidate identity, relevant passing checks, task progress, and explicit integration evidence required by a Change remain the authorities. This avoids interpreting words such as “GitHub Pages” as proof or disproof of a published build.

2. **Write cache exclusions to Git's effective repository exclude file.** Git linked worktrees point `.git` to a worktree Git directory, but Git resolves `info/exclude` through the shared repository metadata. During managed worktree preparation, ask Git for the effective path with `rev-parse --git-path info/exclude` and append the four cache paths idempotently. This intentionally affects all worktrees in the same clone. Do not edit the project's tracked `.gitignore`: exclusions are runtime hygiene, not product policy. Existing Git commands using `--exclude-standard` honor this file; cover the guardian path with focused checks and preserve visibility of unrelated untracked files.

3. **Use a fixed Playwright runtime path.** Add `PLAYWRIGHT_BROWSERS_PATH=/opt/minime/runtime/playwright-browsers` to the environment already constructed for isolated test commands, so resolver inspection and subprocess execution agree. If the directory or required browser is missing, report it unavailable and fail the applicable Playwright check; do not fall back to the host user's cache or download binaries.

4. **Represent contingencies through existing proposal feasibility evidence.** Extend the existing native proposal-feasibility report with a small structured contingency assessment (`status`, `blocking`, explanation, and evidence references) instead of adding a new table or evidence subsystem. The thinking agent may mark `fallback_applied` / `blocking: false` only when an existing local artifact/path and a focused check support the mapped acceptance behavior. The evaluator verifies that references are known and locally present, and that the scenario is mapped to a testable task; insufficient or missing support remains blocking. Update the canonical Change-author skill so proposal authors include the assessment and focused verification. The precise functional mapping remains specific to each Change's acceptance criteria.

## Risks / Trade-offs

- [Risk] Removing publication-claim handling could hide an actual integration requirement if it were judged from task wording alone. → [Mitigation] Do not infer integration success from text; preserve the canonical direct-evidence requirement for any explicitly scoped real integration.
- [Risk] An overly broad exclusion could hide candidate files. → [Mitigation] Add only the four named generated-cache patterns in the clone-local Git exclude file, idempotently; test that unrelated untracked files remain visible.
- [Risk] Runtime path differs across hosts. → [Mitigation] Treat `/opt/minime/runtime/playwright-browsers` as the supported isolated-runner contract and report missing installation explicitly; no home-cache escape hatch.
- [Risk] A fallback is recorded as sufficient without a verifiable behavior check. → [Mitigation] Require local evidence references and a mapped focused check; keep it blocking when evidence is absent or inconclusive.

## Migration Plan

No persistent schema migration is planned. Existing managed worktrees receive exclusions when prepared; Git stores them in the clone's effective `info/exclude`, shared by its linked worktrees. Configure the isolated runner with the canonical browser path and fail with a clear missing-browser result if it is not installed. Rollback consists of reverting the code/skill changes and removing the four dedicated patterns; no project `.gitignore` or durable candidate data is rewritten.

## Removal Ledger

| Replaced behavior | Old entrypoints / consumers | Action | Evidence required |
|---|---|---|---|
| Static publication wording invalidates completed tasks | `_PUBLISHED_CANDIDATE_CLAIM`, `_invalid_published_evidence_completions`, task-completion call sites, tests tied to the rejection | REMOVE the static claim rule; remove helper/marker code only if caller census confirms no independent use | Search all source/test callers; focused regression proving static publication wording passes with valid Git/test evidence and remains non-evidence itself |
| Candidate Playwright resolution can use a user cache | `CandidateTestResolver.inspect_tooling`, test environment construction, related resolver/E2E tests | REPLACE with the isolated runtime path | Focused tests show canonical env/path wins, missing browser fails without fallback/download |
| Worktree caches may appear as untracked blockers | Worktree preparation and Git cleanliness/Commit Guardian checks | ADD the four exclusions to Git's effective repository `info/exclude`; retain existing `--exclude-standard` behavior | Real Git fixture proves four directories are ignored and a neighboring ordinary untracked file remains visible |
| External integration absence is always described as blocking despite a sufficient fallback | Native feasibility report/schema, feasibility evaluator, `minime-openspec-change-author` guidance and its tests | MODIFY existing feasibility/report flow and skill guidance; no new service/table | Focused evaluator test verifies a present fallback path + mapped passing check is `fallback_applied` / non-blocking; missing/insufficient evidence stays blocking |

No database rows, migrations, archived Changes, Run history, or external evidence are to be deleted. No independent old runtime route should remain after the replacement; preserve unrelated publication evidence consumers if the caller census finds any.
