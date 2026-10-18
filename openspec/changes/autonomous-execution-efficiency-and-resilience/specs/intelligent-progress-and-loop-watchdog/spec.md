## Purpose

Provides an intelligent multi-signal activity, progress, and loop watchdog that monitors implementer and execution sub-processes, distinguishing legitimate extended computation or test suites from frozen processes and repetitive non-convergent loops without imposing blunt wall-clock timeouts.

## ADDED Requirements

### Requirement: Multi-signal activity and progress watchdog
The system SHALL monitor active execution attempts using a multi-signal state progression (`RUNNING → SUSPECTED_STALL → STALLED → RECOVERY`). The watchdog SHALL observe tool execution events, child process CPU/IO activity, stdout/stderr streams, disk file mutations, and git worktree status to assess whether an attempt is making active forward progress.

#### Scenario: Complex long-running task with continuous activity is not aborted
- **GIVEN** an implementer running a long execution that exceeds typical duration (e.g. >10 minutes)
- **WHEN** the process produces periodic tool calls, file writes, test outputs, or process tree activity
- **THEN** the watchdog maintains status `RUNNING`, resets inactivity timers, and allows the task to proceed to natural completion without wall-clock abortion.

#### Scenario: Inactivity triggers diagnosis before termination
- **GIVEN** a running implementer sub-process in the sandbox
- **WHEN** no tool invocations, stdout/stderr output, or filesystem mutations are observed for a configurable period (e.g. 3 to 5 minutes)
- **THEN** the watchdog transitions to `SUSPECTED_STALL` and initiates non-destructive diagnostic probes (checking process group existence, thread states, and worktree lock files)
- **AND** the system SHALL NOT terminate the process solely based on stdout silence if sub-process threads are actively consuming compute.

### Requirement: Repetitive loop and zero-diff stagnation detection
The system SHALL detect repetitive non-convergent loops by tracking blocker fingerprints, candidate SHA identicalness, and zero-diff streaks across attempt sub-iterations. When repetitive failure patterns are confirmed, the system SHALL intervene to prevent quota waste.

#### Scenario: Repetitive blocker loop is detected and diverted
- **GIVEN** an active execution job experiencing repeated failures
- **WHEN** the same blocker fingerprint occurs consecutively (`same_blocker_fingerprint_streak >= 3`) or the agent repeatedly modifies and restores files producing identical SHAs with no new evidence
- **THEN** the watchdog marks the state as `STALLED` with diagnostic code `REPETITIVE_LOOP_DETECTED`
- **AND** triggers controlled recovery or stops at `NEEDS_HUMAN` without burning additional inference budget on identical cycles.

#### Scenario: Deadlock or frozen sub-process requires positive deadlock confirmation before termination
- **GIVEN** an execution sub-process exceeding the stall timeout
- **WHEN** consecutive diagnostic probes confirm zero CPU activity, zero CPU time delta, and zero open network sockets across the process tree
- **THEN** only after positive deadlock confirmation across multiple consecutive probes does the watchdog confirm `STALLED`
- **AND** the system cleanly terminates the subprocess group (SIGTERM followed by SIGKILL), records `WATCHDOG_HANG_TERMINATED` with process diagnostics, and preserves candidate and worktree state for safe recovery.
