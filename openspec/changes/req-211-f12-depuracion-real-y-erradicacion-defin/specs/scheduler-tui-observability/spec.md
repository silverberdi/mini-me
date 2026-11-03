# Spec Delta

## REMOVED Requirements

### Requirement: Queue and Scheduler View
**Reason**: The scheduler/queue TUI is an obsolete surface and F12 does not activate a scheduler.
**Migration**: No replacement is introduced; retained operational APIs remain authoritative.

### Requirement: Interactive Explainability and Manual Tick
**Reason**: Manual scheduler ticks and TUI explainability are retired and must not start work.
**Migration**: Use only retained native coordination paths under their existing authorization rules.

