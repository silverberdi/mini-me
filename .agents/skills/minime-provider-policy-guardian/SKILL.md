---
name: minime-provider-policy-guardian
description: Enforce Codex/Antigravity as primary planning and execution providers, DeepSeek Direct as independent reviewer, and OpenRouter as quota-only rescue for in-flight work.
---
# Provider Policy Guardian
Codex and Antigravity are primary planning/execution providers selected by validated per-stage profiles. Either may hand off compatible work to the other only while preserving durable Run/Job/worktree identity, checkpoints, fencing and idempotent side-effect reconciliation. A substantive author never authoritatively reviews the same candidate.

DeepSeek Direct is the independent reviewer for distinct read-only CONTRACT REVIEW and code REVIEW stages. It uses only its own official API/account and budget authority; it never plans, implements, rescues work, substitutes one review for the other, or authorizes APPLY, product decisions or merge. Missing capability, capacity, identity or budget evidence leaves the work waiting; never invent approval or silently substitute a reviewer.

OpenRouter is an exceptional, explicitly authorized and budgeted rescue provider only for work already in flight when both Codex and Antigravity are blocked by quota. It is never a primary executor or reviewer, does not start new READY work, and cannot bypass security, integrity, authorization, compatibility or review gates. Its account, credit, pricing and reservation evidence remain separate from DeepSeek Direct.

Provider capacity/balance evidence is not spend authorization. Reservations identify provider, protected account, model, stage, Run/Job and billing origin. Keep provider adapters extensible without provider-specific branches in orchestration, preserve historical OpenRouter reservations, and never weaken budget or privacy policy.
