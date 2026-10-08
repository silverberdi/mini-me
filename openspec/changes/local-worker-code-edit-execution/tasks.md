# Tasks: Local Worker Code Edit Execution

- [x] 1. Add structured patch contract to `LocalWorkerResult` in `src/minime/local_worker/models.py`
- [x] 2. Implement deterministic patch policy validation in `src/minime/local_worker/patch_applier.py`
- [x] 3. Implement `LocalPatchApplier` using `ManagedWorkspaceGuard` and `WorktreeManager` for authorized execution worktree patch application
- [x] 4. Extend `LocalWorkerService` execution pipeline in `src/minime/local_worker/service.py` to support patch validation, application, baseline cleanup, and single corrective attempt
- [x] 5. Enrich `LocalExecutionEvidence` domain model in `src/minime/local_worker/models.py` with patch application and changed file telemetry
- [x] 6. Add comprehensive unit and integration tests in `tests/test_local_worker_code_edit.py` covering all 20 required isolation, safety, and patch execution scenarios
- [x] 7. Demonstrate `TEST_AUTHORING` task envelope representation for `tests/test_autonomous_intake_admission.py`
