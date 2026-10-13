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

Do not duplicate every `tasks.md` checkbox into GitHub Issues. MM-Rxx backlog dossiers are planning sources; each approved OpenSpec Change should correspond to **one** canonical GitHub Issue and a durable change binding only after de-duplication. The N01 #133/#138 duplicate must be retired carefully without loss of history. Never equate writing docs on a branch with updating GitHub Projects v2/production DB.

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
mini me detects and corroborates human merge, deploys only according to project authorization and verifies **functional** behavior in the destination. OpenSpec sync/archive are performed by **native agent/OpenSpec workflow**, not custom Python merges or shutil-based simulators. If closure creates new tracked Git changes **after** human merge, the design must use a protected-branch-compliant and human-authorized Git route (for example an additional closure PR) or an explicitly approved pre-merge inclusion strategy; no silent direct push to protected main. Then mini me reconciles Issue/Project, finalizes metrics and only cleans safe owned worktrees. DONE requires no unverified closure phase or side effect.
