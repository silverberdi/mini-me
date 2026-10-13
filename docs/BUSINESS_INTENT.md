# Business Intent

## Why mini me exists
Manual use of multiple coding agents creates coordination work: selecting capacity, moving context, controlling scope, tracking retries and quota limits, reviewing changes, validating UI, preparing PRs, deploying candidates and remembering what remains safe to close.

mini me should turn that coordination burden into a small **human decision inbox**. It must not reimplement OpenSpec or produce project code/specs itself; those are the jobs of **agents operating via OpenSpec**.

## Job to be done
> From a GitHub need **or** an implementation-ready OpenSpec change, coordinate authorized AI coding agents that use native OpenSpec workflows to propose, apply, verify, independently review and deliver real software through a human-approved PR/merge; preserve work through failures and quota exhaustion, provide verifiable postdeployment results, and surface only decisions requiring human judgment.

## Product posture
- Personal internal system; not a commercial product.
- One controlled Linux installation.
- Multi-project by domain model from day one.
- Optimize for reliability, traceability, low unnecessary spend and reduced human coordination.
- Do not build multitenancy, generic installer ecosystems, arbitrary deployment backends or enterprise portability unless a later real need appears.

## Success
mini me is successful when a well-defined need reaches a real, independently reviewed PR without manual agent handoffs, and after the human merge the actual deployed behavior is verified and OpenSpec is natively closed. Every Change must deliver a usable vertical capability with stage-level and end-to-end tests. Preserved evidence must prove which agent executed each native OpenSpec workflow and what code, review, audit (if authorized), UI candidate and production behavior resulted. Longer term mini me repeats this on **its own repository** without assuming authority to merge or buy quota.
