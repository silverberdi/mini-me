# Design

## Context
See proposal.md - Why and specs/ delta requirements. Currently in minime/cli/main.py and watchdog_service.py, persistence of a diagnosis in watchdog_repo.save_diagnosis is conditioned on finding an existing prior diagnosis with sre_intervention_transition_key. Because the initial observation is never persisted without a prior match, subsequent observations never find a match either, leaving improvement_suggestion permanently empty in watchdog_diagnoses.

## Goals / Non-Goals
**Goals:**
- Persist Watchdog diagnostic observations in PostgreSQL with their transition/intervention key and event identity unconditionally on first occurrence.
- Enable recurrence evaluation to find earlier persisted records by transition/intervention key without requiring pre-existing diagnoses.
- Store semantic improvement suggestions with status pending in watchdog_diagnoses.
- Expose pending suggestions in /api/v1/admin/watchdog/diagnoses and the /mejora-continua UI feed.

**Non-Goals:**
- Creating autonomous GitHub issues or bypassing operator review.
- Changing production database schemas outside conservative Alembic migrations.

## Decisions
1. **Unconditional Diagnosis Persistence with Idempotency**:
   - Persist diagnoses upon occurrence using (run_id, stage, event_identity) uniqueness instead of gating on prior patterns.
   - Alternatives considered: keeping the circular check and seeding a synthetic record (rejected: falsifies history).
2. **Explicit Transition and Intervention Key Indexing**:
   - Retain transition_key in the diagnostic payload so queries by key find the exact event family across runs.
3. **Pending Status for Cataloged Suggestions**:
   - Newly stored suggestions default to status 'pending' so the admin API and dashboard display them for operator evaluation.

## Risks / Trade-offs
- [Risk] Duplicate diagnostic records during retries -> [Mitigation] Enforce event identity idempotency in PostgresWatchdogRepository.save_diagnosis.
- [Risk] Unbounded table growth -> [Mitigation] Retain existing cleanup/retention policies; diagnostic rows remain bounded per run/stage.
