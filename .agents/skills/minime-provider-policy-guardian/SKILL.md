---
name: minime-provider-policy-guardian
description: Enforce Codex/Antigravity as primary planning and execution providers, DeepSeek Direct as independent reviewer, and OpenRouter as quota-only rescue for in-flight work.
---
# Provider Policy Guardian
Codex and Antigravity are primary planning/execution providers selected by validated per-stage profiles. Either may hand off compatible work to the other only while preserving durable Run/Job/worktree identity, checkpoints, fencing and idempotent side-effect reconciliation. A substantive author never authoritatively reviews the same candidate.

DeepSeek Direct is the independent reviewer for distinct read-only CONTRACT REVIEW and code REVIEW stages. It uses only its own official API/account, fresh capacity/balance evidence, and the owner's applicable spending policy; it never plans, implements, rescues work, substitutes one review for the other, or authorizes APPLY, product decisions or merge. Ordinary calls need no new per-call human approval when that policy permits them. Missing capability, capacity, identity or applicable policy leaves the work waiting; never invent approval or silently substitute a reviewer. Record provider-reported usage durably and retain unknown settlement as unresolved exposure.

OpenRouter is an exceptional rescue provider only for work already in flight when both Codex and Antigravity are blocked by quota, subject to its own capacity evidence and the owner's applicable OpenRouter spending policy. It is never a primary executor or reviewer, does not start new READY work, and cannot bypass security, integrity, compatibility or review gates. Its account, credit, pricing and usage evidence remain separate from DeepSeek Direct.

Provider capacity/balance evidence does not override the owner's spending policy or guarantee unlimited coverage. Use optional configured limits and reservations where policy or provider semantics require them, rather than requiring a new approval or maximum for every call. Record actual provider usage durably and idempotently; preserve unresolved exposure without inventing settlement. Keep provider adapters extensible without provider-specific branches in orchestration, preserve historical OpenRouter reservations, and never weaken security, privacy or configured spending policy.
