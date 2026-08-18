# GitHub Work Management

## Topology
One global GitHub Project under the owner's personal account. Issues remain in the repository that owns the work.

## Source-of-truth rule
GitHub Project fields are for planning/visualization. Runtime repository selection derives only from validated durable project binding.

Required logical binding:
`project_id ↔ repository identity ↔ GitHub issue ↔ OpenSpec change`.

## Suggested Project fields
- Status: Backlog / Ready / In Progress / Human Review / Blocked / Done / Closed
- Priority: P0/P1/P2/P3
- Stage
- OpenSpec Change
- Project (display only)
- Type: Feature/Bug/Improvement/Tech Debt
- Complexity: S/M/L
- Executor
- Reviewer
- Outcome
- Started
- Completed

Do not duplicate every `tasks.md` checkbox into GitHub Issues.

## Status mapping
- DISCOVERED → Backlog
- READY → Ready
- IN_PROGRESS → In Progress
- NEEDS_HUMAN / MERGE_PENDING → Human Review
- BLOCKED → Blocked
- DONE → Done
- REJECTED/CANCELLED → Closed

## PR lifecycle
A candidate should be committed/pushed and represented by a **draft PR before UI human validation**, so validation is tied to an exact head/base identity. After successful human approval the PR may become ready for human merge.

## Post-merge
mini me detects merge, deploys production according to project policy, verifies it, archives OpenSpec, closes/synchronizes Issue/Project state, finalizes metrics and cleans the worktree.
