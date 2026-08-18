---
name: minime-repository-binding-guard
description: Protect exact project/repository/worktree identity before implementation, push or PR operations.
---
# Repository Binding Guard
Repository authority comes only from durable project binding. Never infer from issue title/label/Project display fields. Before write execution and before push/PR, verify expected repo remote, project id, base branch/SHA, change id and assigned worktree. Mismatch is blocking. Never change origin to make a check pass.
