# Tasks: Fail-Closed External Evidence and Actions

- [ ] 1. Complete comprehensive codebase inventory of external-effect APIs, `bool`-only success returns, and fabricated-success defaults across adapters and services.
- [ ] 2. Define generic `ExternalActionResult[T]` outcome container and `ExternalOutcome` enum (`SUCCESS`, `FAILURE`, `UNKNOWN`, `AMBIGUOUS`) in `src/minime/domain/models.py` and `enums.py`.
- [ ] 3. Extend `ExternalActionType` and align `ExternalActionStatus` enums in domain and database models to support generic external side-effect tracking.
- [ ] 4. Remove all fabricated default success returns (`return True` on exception, `PVTI_mock_*`, dummy issue `#1`, synthetic URLs) from `GitHubAdapter` and `ReadinessGitHubStub`.
- [ ] 5. Migrate `GitHubAdapter` REST and CLI methods to return typed `ExternalActionResult[T]` with observe-before-act deduplication and postcondition verification.
- [ ] 6. Migrate Git operations in `src/minime/utils/git.py`, `post_merge_service.py`, and `orchestration_service.py` to check return codes and verify exact SHA/ref evidence fail-closed.
- [ ] 7. Migrate OpenSpec filesystem operations (`OpenSpecSyncService`, `OpenSpecArchiveService`, `OpenSpecValidationService`) to confirm verifiable postconditions.
- [ ] 8. Migrate provider execution runners (`DeepSeekAuditorRunner`, `ImplementerRunner`, `CodexProviderService`) to verify output artifact sufficiency alongside process exit code 0.
- [ ] 9. Implement explicit separation between deployment execution action success (`DEPLOY_ACTION_SUCCESS`) and production health reachability (`PRODUCTION_VERIFIED` vs `UNKNOWN`).
- [ ] 10. Implement generic observe-before-repeat idempotency primitive in `OrchestrationExternalActionRepository` for retrying ambiguous or unknown external side effects.
- [ ] 11. Migrate `PostMergeService` external action consumption to use typed outcome results and fail-closed re-observation without fabricating phase booleans.
- [ ] 12. Migrate domain callers (`ReadinessService`, `IntakeService`, `OrchestrationService`, `ContainerPreviewService`, and API endpoints) to handle `ExternalActionResult[T]` fail closed.
- [ ] 13. Add adversarial unit tests for `GitHubAdapter` covering network timeouts, 401/403/404 HTTP errors, rate limits, and unparseable JSON.
- [ ] 14. Add observe-before-repeat idempotency tests for Git pushes, PR creations, issue operations, and branch cleanup.
- [ ] 15. Add regression tests ensuring zero synthetic IDs, dummy issue numbers, or `return True` fallback paths remain in production execution.
- [ ] 16. Perform exhaustive codebase search and audit verifying no unmigrated `bool`-only or fabricated external action paths remain in `src/minime/`.
- [ ] 17. Execute Ruff linter, focused test suite, full pytest suite, strict OpenSpec validation, and candidate-bound review evidence.
