# Design: Fail-Closed External Evidence and Actions

## Architectural Laws

- **LAW 1: No external evidence -> no success.** An external operation or query MUST NOT be classified as successful without positive, verifiable evidence of postconditions (`UNKNOWN != SUCCESS`, `FAILURE != SUCCESS`, `AMBIGUOUS != SUCCESS`).
- **LAW 2: Unknown is a first-class outcome.** Network timeouts, HTTP 50x errors, 429 rate limits, unparseable responses, missing authorizations, and unobservable states MUST produce an explicit `UNKNOWN` or `AMBIGUOUS` outcome rather than silent fallback or boolean `False`/`True`.
- **LAW 3: Ambiguous side effects are observed before repeat.** When a prior side-effect attempt returned `UNKNOWN` or `AMBIGUOUS`, subsequent retries MUST observe remote external state before attempting to re-issue non-idempotent operations.
- **LAW 4: External identity must be observed, never invented.** Adapters MUST NOT return synthetic IDs (e.g. `PVTI_mock_2`), dummy issue numbers (`issue #1`), or fake URLs (`https://github.com/.../issues/1`) in production code paths.
- **LAW 5: Command acceptance != postcondition verification.** Subprocess return code 0 or HTTP 202 Accepted indicates request receipt, not postcondition fulfillment. Crucial side effects (e.g. deployment, PR merge, branch deletion) MUST verify postcondition state when required.
- **LAW 6: Production/test fakes are strictly separated.** Mocks, stubs, and synthetic test fixtures are permitted exclusively within test suites (e.g. `tests/conftest.py`). Production adapters MUST NOT contain embedded fallback mocks.
- **LAW 7: External adapters report truth; lifecycle/sagas decide policy.** Adapters return typed outcome reports (`ExternalActionResult[T]`). Adapters do not mutate domain lifecycle or make policy decisions; domain services consume typed outcomes and execute fail-closed transitions via `LifecycleTransitionAuthority`.

## Typed External Outcome Model

All external adapters (`GitHubAdapter`, Git execution utilities, OpenSpec handlers, Provider runners, Deployment wrappers) will return a unified, generic outcome container:

```python
from enum import Enum
from typing import Generic, TypeVar, Any
from datetime import datetime
from pydantic import BaseModel, Field

class ExternalOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    UNKNOWN = "UNKNOWN"
    AMBIGUOUS = "AMBIGUOUS"

T = TypeVar("T")

class ExternalActionResult(BaseModel, Generic[T]):
    """Unified fail-closed result container for external operations and queries."""
    outcome: ExternalOutcome
    data: T | None = None
    observed_evidence: dict[str, Any] = Field(default_factory=dict)
    reason_code: str = "ok"
    error_message: str | None = None
    external_id: str | None = None
    retry_safe: bool = True
    timestamp: datetime = Field(default_factory=utc_now)
    source_adapter: str = "github"

    @property
    def is_success(self) -> bool:
        return self.outcome == ExternalOutcome.SUCCESS

    @property
    def is_failure(self) -> bool:
        return self.outcome == ExternalOutcome.FAILURE

    @property
    def is_unknown_or_ambiguous(self) -> bool:
        return self.outcome in (ExternalOutcome.UNKNOWN, ExternalOutcome.AMBIGUOUS)
```

## Production Writer & Adapter Inventory

### 1. GitHub Adapter (`src/minime/adapters/github.py` & `src/minime/domain/interfaces.py`)

| Method Name | Current Signature / Behavior | Fabricated Success Default | Stage B Fail-Closed Migration |
|---|---|---|---|
| `verify_repository` | returns `tuple[bool, str \| None]` | None (returns 404/error string), but HTTP 500 raises | Return `ExternalActionResult[bool]`; 401/403 -> `FAILURE` (auth), 500/429 -> `UNKNOWN` |
| `validate_issue_binding` | returns `tuple[bool, str \| None]` | Raises exception on HTTP error | Return `ExternalActionResult[bool]`; 404 -> `FAILURE`, 500/429 -> `UNKNOWN` |
| `list_issues` | returns `list[dict]` | Returns empty list `[]` on REST & CLI failure | Return `ExternalActionResult[list[dict]]`; failure/unobservable -> `UNKNOWN` with empty list data |
| `list_project_items` | returns `list[dict]` | Returns empty list `[]` on CLI failure | Return `ExternalActionResult[list[dict]]`; failure -> `UNKNOWN` |
| `create_issue` | returns `dict[str, Any]` | Returns `{"number": 1, ...}` fallback double when REST & CLI fail! | Return `ExternalActionResult[dict]`; deduct existing by title first; if timeout/unobservable -> `AMBIGUOUS`; NEVER return fake issue #1 |
| `add_issue_to_project` | returns `str \| None` | Returns `f"PVTI_mock_{project_number}"` on CLI error! | Return `ExternalActionResult[str]`; if CLI fails -> `FAILURE`/`UNKNOWN`; NEVER return `PVTI_mock_*` |
| `get_pull_request` | returns `PullRequestLookupResult` | Uses enum lookup result | Return `ExternalActionResult[dict]`; align with `FOUND_EXACT` -> `SUCCESS`, `NOT_FOUND` -> `FAILURE`, `UNOBSERVABLE`/`AMBIGUOUS` -> `UNKNOWN`/`AMBIGUOUS` |
| `create_pull_request` | returns `dict[str, Any]` | Raises `RuntimeError` | Return `ExternalActionResult[dict]`; timeout after POST -> `AMBIGUOUS` (re-check GET PR by head branch) |
| `push_branch` | returns `bool` | Raises `RuntimeError` | Return `ExternalActionResult[str]` with pushed commit SHA evidence |
| `get_remote_branch_head` | returns `str \| None` | Returns `None` on missing ref or failure | Return `ExternalActionResult[str]`; branch absent -> `FAILURE` (not found), git error -> `UNKNOWN` |
| `get_pull_request_details` | returns `dict[str, Any]` | Raises `RuntimeError` on 404 / 400 | Return `ExternalActionResult[dict]`; 404 -> `FAILURE`, 500 -> `UNKNOWN` |
| `close_issue` | returns `bool` | Returns `True` on 404 or exception! | Return `ExternalActionResult[bool]`; GET issue first: if already closed -> `SUCCESS`, 404 -> `FAILURE` (not found), exception -> `UNKNOWN`; NEVER return `True` on error |
| `update_project_item_status` | returns `bool` | Returns `True` even if `gh project item-edit` fails! | Return `ExternalActionResult[bool]`; check `res.returncode == 0` -> `SUCCESS`, CLI failure -> `FAILURE`/`UNKNOWN`; NEVER return `True` on error |
| `delete_remote_branch` | returns `bool` | Returns `True` even if DELETE fails or throws! | Return `ExternalActionResult[bool]`; HTTP 200/204/404 -> `SUCCESS` (idempotently deleted), 401/403 -> `FAILURE`, 500 -> `UNKNOWN`; NEVER return `True` on exception |

### 2. Git Execution Utilities (`src/minime/utils/git.py`, `post_merge_service.py`, `orchestration_service.py`)

- `verify_candidate_ancestry`: Currently runs `git merge-base --is-ancestor` with `check=False` and returns `res.returncode == 0` or catches `Exception` returning `False`.
  - *Migration*: Return `ExternalActionResult[bool]`. Explicitly verify that `git fetch origin` succeeded or that local refs are observable. If git command fails due to corrupted ref or missing commit object, report `UNKNOWN` rather than simple `False`.
- `push_branch`: Verify `candidate_sha` exists locally, verify remote authorization bundle, check `result.returncode == 0`, and observe remote branch head via `ls-remote` postcondition verification.
- `clean_worktree_and_branches`: Check return codes for `git worktree remove` and `git branch -D`. Report explicit cleanup outcome rather than swallowing errors with logger warnings.

### 3. OpenSpec Filesystem & CLI Operations (`OpenSpecSyncService`, `OpenSpecArchiveService`, `OpenSpecValidationService`)

- `OpenSpecSyncService`: Commands returning 0 are verified against filesystem postconditions (`spec.md` exists and contains valid `## Requirements` section).
- `OpenSpecArchiveService`: Verify directory relocation postcondition (`openspec/changes/archive/YYYY-MM-DD-<name>` exists and source directory in `openspec/changes/` is absent). If move is partial, return `AMBIGUOUS`.

### 4. Provider & Execution Operations (`DeepSeekAuditorRunner`, `ImplementerRunner`, `CodexProviderService`)

- Process exit code 0 is required BUT NOT sufficient for success.
- Must verify that required output artifact (e.g. review verdict JSON, patch file, or report file) exists, is non-empty, and is validly parseable.
- If process exits 0 but output artifact is missing or invalid: return `outcome = UNKNOWN`, `reason_code = "EVIDENCE_INSUFFICIENT"`, triggering `NEEDS_HUMAN` gate in domain callers.

### 5. Deployment & Service Operations (`deploy_update.sh`, `ContainerPreviewService`)

- Distinguish `DEPLOY_ACTION_SUCCESS` (deployment script executed with exit code 0) from `PRODUCTION_VERIFIED` (HTTP health check endpoint returned 200 OK with expected version/SHA payload).
- If deploy script returns 0 but health check endpoint is unreachable or times out: report `action_outcome = SUCCESS`, `production_verification = UNKNOWN`.

### 6. Caller Inventory & Fail-Closed Behavior

- `PostMergeService`: Refactored to consume `ExternalActionResult` for PR lookup, ancestry verification, issue closure, project item update, and branch deletion. Does NOT return synthetic `all_phases = True`. Re-observes remote state on repeated invocations.
- `ReadinessService`: Evaluates external GitHub and Git bindings fail closed. Unobservable repositories or issues yield `readiness_state = NOT_READY` / `UNKNOWN` evidence reasons without mutating state.
- `IntakeService`: Consumes `ExternalActionResult` from issue creation and project item addition. If creation returns `AMBIGUOUS` or `UNKNOWN`, retains item in `PREPARING` without fabricating fake issue #1 or mock project item IDs.
- `OrchestrationService`: Checks `ExternalActionResult` on push and PR creation. Uses `OrchestrationExternalAction` reservation to observe-before-repeat when retrying after `AMBIGUOUS` outcome.

## Extension of `OrchestrationExternalAction` & `ExternalActionStatus`

To support generic observe-before-repeat idempotency across all external side effects, `ExternalActionType` in `src/minime/domain/enums.py` will be extended:

```python
class ExternalActionType(str, Enum):
    BRANCH_PUSH = "BRANCH_PUSH"
    PR_CREATE = "PR_CREATE"
    ISSUE_CREATE = "ISSUE_CREATE"
    ISSUE_CLOSE = "ISSUE_CLOSE"
    PROJECT_ITEM_ADD = "PROJECT_ITEM_ADD"
    PROJECT_ITEM_EDIT = "PROJECT_ITEM_EDIT"
    BRANCH_DELETE = "BRANCH_DELETE"
    OPENSPEC_SYNC = "OPENSPEC_SYNC"
    OPENSPEC_ARCHIVE = "OPENSPEC_ARCHIVE"
    DEPLOY_EXECUTE = "DEPLOY_EXECUTE"
    SERVICE_RESTART = "SERVICE_RESTART"
```

And `ExternalActionStatus` values are aligned: `RESERVED`, `EXECUTING`, `COMPLETED`, `FAILED`, `AMBIGUOUS`, `UNKNOWN`.

Before executing any mutating external action, `OrchestrationExternalActionRepository` is queried by `action_key`:
1. If existing action is `COMPLETED`: return stored `remote_identifier` / `result_payload` immediately (idempotent skip).
2. If existing action is `AMBIGUOUS` or `UNKNOWN`: execute observation query on external system (e.g. check if issue/PR/branch already exists). If observed present, transition action to `COMPLETED` and return. If observed absent, retry execution.
3. If no action exists: reserve action record (`RESERVED`), execute operation, record typed result (`COMPLETED`, `FAILED`, or `AMBIGUOUS`).

## PostMerge Temporary Contract

In Stage B, `PostMergeService` is updated to consume `ExternalActionResult` for all external operations. When invoked repeatedly:
- It MUST re-query remote GitHub issue and PR status via `GitHubAdapter` rather than relying on in-memory boolean flags.
- If issue closure or project item update returns `UNKNOWN`, it records the failure in reconciliation result logs and keeps the phase marked unverified.
- Full saga durability belongs to Stage D, but Stage B guarantees that `PostMergeService` never fabricates false closure booleans.

## Test Strategy

- **Isolated Test Fixtures**: All fake/stub adapters (e.g. `ReadinessGitHubStub`) will be strictly scoped to `tests/conftest.py` and test modules.
- **Adapter Adversarial Unit Tests**:
  - Test `GitHubAdapter.create_issue` on timeout -> returns `AMBIGUOUS`, zero fake issue #1.
  - Test `GitHubAdapter.close_issue` on 404 -> returns `FAILURE`, zero `True` return.
  - Test `GitHubAdapter.add_issue_to_project` on CLI error -> returns `FAILURE`, zero `PVTI_mock_*` ID.
  - Test `GitHubAdapter.update_project_item_status` on CLI error -> returns `FAILURE`, zero `True` return.
  - Test `GitHubAdapter.delete_remote_branch` on error -> returns `FAILURE`/`UNKNOWN`, zero `True` return.
  - Test Git ancestry on corrupted ref -> returns `UNKNOWN`.
  - Test Provider execution on exit 0 with missing output file -> returns `UNKNOWN` (`EVIDENCE_INSUFFICIENT`).
  - Test Deployment action success with unreachable endpoint -> returns `DEPLOY_ACTION_SUCCESS` with `PRODUCTION_VERIFIED = UNKNOWN`.
