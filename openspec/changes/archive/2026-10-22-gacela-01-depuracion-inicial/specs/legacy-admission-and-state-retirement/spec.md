## Purpose

Reduces inherited local scheduling and persistence to the minimum safe state without losing data required for authentication, repository safety, or recovery.

## ADDED Requirements

### Requirement: No duplicate local ticket queue or synthetic prioritization
mini me SHALL NOT maintain an operational backlog copy, work queue, priority score, roadmap rank, or scheduler decision as an authority for selecting work. It SHALL NOT autonomously start, admit, rank, or schedule work during F1.

#### Scenario: Scheduler tick is requested
- **WHEN** an API, CLI, service, or background process requests a scheduler tick or fresh work admission
- **THEN** mini me SHALL return an explicit disabled result
- **AND** SHALL NOT create a job, run, queue item, provider invocation, or external side effect.

#### Scenario: Legacy queue data exists during migration
- **WHEN** existing local queue or backlog records are found before schema retirement
- **THEN** migration preflight SHALL classify their references and retention need before any destructive operation
- **AND** the records SHALL NOT be used to select or start work.

### Requirement: Destructive schema retirement is recoverable and evidence-based
mini me SHALL remove a PostgreSQL structure only after a versioned Alembic migration has recorded its dependency inventory, protected data needed by retained capabilities, and provided a verified rollback or restoration procedure. Applied historical migrations and retained operational evidence SHALL NOT be edited or erased.

#### Scenario: Candidate table has a retained dependency
- **WHEN** the removal inventory finds a live caller, foreign-key dependency, recovery need, or required historical evidence for a candidate table or column
- **THEN** the migration SHALL NOT drop it in F1
- **AND** the implementation SHALL record it as RETAIN-WITH-REASON or reserve it for the applicable later phase.

#### Scenario: Approved obsolete structure is removed
- **WHEN** the inventory proves that a legacy-only structure has no retained dependency and its data has no preservation requirement
- **THEN** a new Alembic revision SHALL remove it without rewriting historical migrations
- **AND** rollback verification SHALL restore the schema and any required safeguarded data path.

### Requirement: Minimum safety state is preserved
mini me SHALL preserve authentication, project configuration that remains useful, Git/GitHub binding safeguards, worktree isolation, secret protection, authorized human decisions, and continuity records that still have retained consumers.

#### Scenario: F1 cleanup runs against an existing installation
- **WHEN** the F1 migration and retirement steps are applied to a populated PostgreSQL installation
- **THEN** retained authentication and repository/worktree safety operations SHALL remain usable
- **AND** no operation SHALL expose secret material or silently discard required continuity evidence.

