# Git and Workspace Policy

- One dedicated worktree/branch per active change.
- Branch convention: `minime/<change-id>-<slug>` unless a project overrides with an explicit safe convention.
- Persist exact base SHA before execution.
- Never reuse a worktree between changes.
- Agent must not alter origin, registered repository or base branch.
- Repository identity is checked before execution and again before push/PR.
- Commit messages should be concise and traceable, e.g. `feat(MM-001): establish durable foundation`.
- A PR is mandatory for executable changes.
- PR body links Issue, OpenSpec change, checks, reviewer, audit, human validation/evidence and candidate SHA.
- Merge is human-only in MVP.
- After confirmed merge and successful closure, clean local worktree/branch; remote branch may be removed when safely merged.
