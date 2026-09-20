# Tasks: Canonical Lifecycle Transition Authority

1. Define Change and WorkItem transition matrices; terminal-state tests.
2. Implement LifecycleTransitionAuthority with expected-state semantics and atomic transition evidence.
3. Centralize explicit flush/read-after-write behavior under `autoflush=False`.
4. Make readiness lifecycle side-effect-free; route authorized transition via authority.
5. Prevent discovery from resurrecting terminal work; emit blocking contradiction.
6. Make queue projection non-authoritative and rebuild-safe.
7. Stop backlog completion from being inferred solely from filesystem/archive presence.
8. Harden fresh admission with atomic READY -> ADMITTED and duplicate prevention.
9. Route relevant recovery/control-plane Change/Backlog writes through authority.
10. Prove affected GET/read surfaces create zero lifecycle transitions.
11. Add adversarial cross-service tests: terminal+active OpenSpec, terminal+reopened Issue,
    terminal+READY queue, stale state, queue rebuild, concurrent admission, restart recovery,
    explicit flush visibility.
12. Run Ruff, focused tests, full pytest, strict OpenSpec validation, and candidate-bound review evidence.

Do not implement Program B–J opportunistically.
