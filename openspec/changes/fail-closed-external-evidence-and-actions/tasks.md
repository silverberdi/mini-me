# Tasks: Fail-Closed External Evidence and Actions

- [x] 1. Complete comprehensive codebase inventory of external-effect APIs, `bool`-only success returns, and fabricated-success defaults across adapters and services.
- [x] 2. Define generic `ExternalActionResult[T]` outcome container, `ExternalOutcome` enum (`SUCCESS`, `FAILURE`, `UNKNOWN`, `AMBIGUOUS`), `RetrySafety` enum (`SAFE`, `UNSAFE`, `UNKNOWN`), strictly typed `ExternalReasonCode` enum, and optional `provider_detail` field in `src/minime/domain/models.py` and `enums.py`.
- [x] 3. Extend `ExternalActionType` and align `ExternalActionStatus` enums in domain and database models to support generic external side-effect tracking and state machine transitions.
- [x] 4. Remove all fabricated default success returns (`return True` on exception, `PVTI_mock_*`, dummy issue `#1`, synthetic URLs, default `"ok"`/`"github"` params) from `GitHubAdapter` and `ReadinessGitHubStub`.
- [x] 5. Implement deterministic `operation_key` generation and HTML comment marker (`<!-- minime-opkey: <key> -->`) deduplication in `GitHubAdapter`, replacing title-only issue matching.
- [x] 6. Migrate `GitHubAdapter` REST and CLI methods (including fail-closed Project item lookup/binding returning `AMBIGUOUS` on mutating CLI error and `FAILURE` on auth rejection) to return typed `ExternalActionResult[T]`.
- [x] 7. Migrate Git operations in `src/minime/utils/git.py`, `post_merge_service.py`, and `orchestration_service.py` to verify explicit return codes, SHA ancestry, and ref presence fail-closed.
- [x] 8. Implement fail-closed `delete_remote_branch` logic requiring authoritative ref absence observation via `ls-remote` under valid authorization before returning `SUCCESS` (`ALREADY_ABSENT`, `retry_safety = UNSAFE`).
- [x] 9. Migrate OpenSpec filesystem operations (`OpenSpecSyncService`, `OpenSpecArchiveService`, `OpenSpecValidationService`) to confirm verifiable postconditions on disk.
- [x] 10. Migrate provider execution runners (`DeepSeekAuditorRunner`, `ImplementerRunner`, `CodexProviderService`) to verify output artifact sufficiency (`EVIDENCE_INSUFFICIENT` -> `UNKNOWN`) alongside process exit code 0.
- [x] 11. Implement explicit separation between deployment execution action success (`DEPLOY_ACTION_SUCCESS`) and production health reachability truth (`PRODUCTION_VERIFIED` vs `UNKNOWN`).
- [x] 12. Implement the 5-step observe-before-repeat protocol in `OrchestrationExternalActionRepository` for retrying ambiguous or unknown external side effects without assuming absent == safe.
- [x] 13. Differentiate historical action execution evidence (`OrchestrationExternalAction` in `COMPLETED`) from current-state remote observation in `PostMergeService` and caller reconciliations.
- [x] 14. Migrate domain callers (`ReadinessService`, `IntakeService`, `OrchestrationService`, `ContainerPreviewService`, and API endpoints) to handle `ExternalActionResult[T]` fail closed.
- [x] 15. Add adversarial unit tests for `GitHubAdapter` covering POST/GET timeouts, 401/403/404 HTTP errors, malformed JSON responses, Project item lookup absence/errors, and branch deletion edge cases.
- [x] 16. Add observe-before-repeat idempotency tests for Git pushes, PR creations, issue operations, and branch cleanup, proving unproven retries remain strictly blocked.
- [x] 17. Perform exhaustive codebase search and audit verifying no unmigrated `bool`-only or fabricated external action paths remain, followed by Ruff, pytest suite, and strict OpenSpec validation.
