# Design: Fail-Closed External Evidence and Actions

## Architectural Laws

- **LAW 1: No external evidence -> no success.** An external operation or query MUST NOT be classified as successful without positive, verifiable evidence of postconditions (`UNKNOWN != SUCCESS`, `FAILURE != SUCCESS`, `AMBIGUOUS != SUCCESS`).
- **LAW 2: Unknown is a first-class outcome.** Network timeouts, HTTP 50x errors, 429 rate limits, unparseable responses, missing authorizations, and unobservable states MUST produce an explicit `UNKNOWN` or `AMBIGUOUS` outcome rather than silent fallback or boolean `False`/`True`.
- **LAW 3: Ambiguous side effects are observed before repeat.** When a prior side-effect attempt returned `UNKNOWN` or `AMBIGUOUS`, subsequent retries MUST observe remote external state before attempting to re-issue non-idempotent operations.
- **LAW 4: External identity must be observed, never invented.** Adapters MUST NOT return synthetic IDs (e.g. `PVTI_mock_2`), dummy issue numbers (`issue #1`), or fake URLs (`https://github.com/.../issues/1`) in production code paths.
- **LAW 5: Command acceptance != postcondition verification.** Subprocess return code 0 or HTTP 202 Accepted indicates request receipt, not postcondition fulfillment. Crucial side effects (e.g. deployment, PR merge, branch deletion) MUST verify postcondition state when required.
- **LAW 6: Production/test fakes are strictly separated.** Mocks, stubs, and synthetic test fixtures are permitted exclusively within test suites (e.g. `tests/conftest.py`). Production adapters MUST NOT contain embedded fallback mocks.
- **LAW 7: External adapters report truth; lifecycle/sagas decide policy.** Adapters return typed outcome reports (`ExternalActionResult[T]`). Adapters do not mutate domain lifecycle or make policy decisions; domain services consume typed outcomes and execute fail-closed transitions via `LifecycleTransitionAuthority`.
- **LAW 8: Retry safety fails closed.** Retry safety defaults to `RetrySafety.UNKNOWN`. Automatic repetition of a mutating side effect is strictly FORBIDDEN unless explicit authoritative evidence proves retry is `RetrySafety.SAFE`.
- **LAW 9: Historical action evidence != current remote truth.** Stored `COMPLETED` action records prove historical side-effect execution and prevent duplicate calls, but MUST NOT substitute for current-state observation when a caller requires current remote truth.
- **LAW 10: Idempotency identity must be bound to operation keys.** Resource creation and lookup MUST be bound to a stable `operation_key` (project, action type, logical target, generation). Title-only issue deduplication is strictly FORBIDDEN.

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

class RetrySafety(str, Enum):
    SAFE = "SAFE"
    UNSAFE = "UNSAFE"
    UNKNOWN = "UNKNOWN"

class ExternalReasonCode(str, Enum):
    AUTH_REQUIRED = "AUTH_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    UNOBSERVABLE = "UNOBSERVABLE"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    NOT_FOUND = "NOT_FOUND"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    ALREADY_CLOSED = "ALREADY_CLOSED"
    ALREADY_ABSENT = "ALREADY_ABSENT"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    UNSUPPORTED = "UNSUPPORTED"
    POSTCONDITION_NOT_PROVEN = "POSTCONDITION_NOT_PROVEN"
    CONFLICT = "CONFLICT"
    REUSED_EXISTING = "REUSED_EXISTING"
    EXECUTION_SUCCESS = "EXECUTION_SUCCESS"

T = TypeVar("T")

class ExternalActionResult(BaseModel, Generic[T]):
    """Unified fail-closed result container for external operations and queries."""
    outcome: ExternalOutcome
    source_adapter: str  # Required field: e.g. 'github_rest', 'git_cli', 'openspec_fs'
    reason_code: ExternalReasonCode | str  # Required field: explicit typed reason
    retry_safety: RetrySafety = RetrySafety.UNKNOWN  # Default fails closed!
    data: T | None = None
    observed_evidence: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    external_id: str | None = None
    operation_key: str | None = None
    timestamp: datetime = Field(default_factory=utc_now)

    @property
    def is_success(self) -> bool:
        return self.outcome == ExternalOutcome.SUCCESS

    @property
    def is_failure(self) -> bool:
        return self.outcome == ExternalOutcome.FAILURE

    @property
    def is_unknown_or_ambiguous(self) -> bool:
        return self.outcome in (ExternalOutcome.UNKNOWN, ExternalOutcome.AMBIGUOUS)

    @property
    def is_retry_authorized(self) -> bool:
        return self.retry_safety == RetrySafety.SAFE
```

## Deterministic Outcome Classification Rules

Implementations MUST classify outcomes deterministically according to the following strict rules:

| Category | Triggering Condition | Outcome | Retry Safety | Typed Reason Code |
|---|---|---|---|---|
| **Authoritative Observation** | Postcondition positively verified by remote API/git/fs | `SUCCESS` | `SAFE` | `EXECUTION_SUCCESS` or `ALREADY_*` |
| **Existing Identity Match** | Existing remote resource bound to exact `operation_key` observed | `SUCCESS` | `SAFE` | `REUSED_EXISTING` |
| **Confirmed Rejection** | HTTP 401/403 (unauthorized) before mutation accepted | `FAILURE` | `UNSAFE` | `AUTH_REQUIRED` |
| **Confirmed Absence / 404** | Authoritative GET query confirms resource does not exist | `FAILURE` | `SAFE` | `NOT_FOUND` |
| **GET / Read Timeout** | Read-only GET query times out before response | `UNKNOWN` | `SAFE` | `TIMEOUT` |
| **Malformed Read Query** | Read-only response JSON/payload is unparseable | `UNKNOWN` | `SAFE` | `MALFORMED_RESPONSE` |
| **Exit 0 Missing Artifact** | Provider process exits 0 but required output file missing | `UNKNOWN` | `UNSAFE` | `EVIDENCE_INSUFFICIENT` |
| **POST / Mutating Timeout** | POST/PATCH/DELETE request times out after transmission | `AMBIGUOUS` | `UNKNOWN` | `TIMEOUT` |
| **Malformed Mutating Resp** | Mutating request sent but response JSON unparseable | `AMBIGUOUS` | `UNKNOWN` | `MALFORMED_RESPONSE` |
| **Deploy Action Success** | Deploy script returns exit 0, health endpoint unreachable | `SUCCESS` (action) / `UNKNOWN` (prod) | `UNKNOWN` | `POSTCONDITION_NOT_PROVEN` |

## Observe-Before-Repeat Protocol

When an external action is in state `AMBIGUOUS` or `UNKNOWN`, retrying or repeating the operation MUST follow this 5-step fail-closed protocol:

1. **Perform action-specific authoritative observation**: Query remote REST API, `git ls-remote`, or filesystem using the exact `operation_key` or target ref identity.
2. **If postcondition positively observed**: Transition action status to `COMPLETED` and return `ExternalActionResult(outcome=SUCCESS, reason_code=REUSED_EXISTING)`.
3. **If authoritative evidence proves the effect did NOT occur AND `retry_safety == RetrySafety.SAFE`**: Retry MAY be authorized by re-issuing `RESERVED` -> `EXECUTING`.
4. **If observation is `UNKNOWN` or `AMBIGUOUS`**: DO NOT repeat automatically. Action remains `AMBIGUOUS` / `UNKNOWN`.
5. **If absence is not conclusive or operation identity is not strong enough**: DO NOT repeat automatically; remain `UNKNOWN` or `AMBIGUOUS` and escalate to caller policy / `NEEDS_HUMAN` gate.

> [!IMPORTANT]
> "No result found" MUST NOT automatically mean "safe to retry". Absence must be authoritatively proven under valid authentication and observable repository binding.

## Operation Identity (`operation_key`) & Marker Specification

Title-only matching for GitHub Issue deduplication is strictly FORBIDDEN.

All mutating external operations MUST generate a deterministic `operation_key` constructed as:
`operation_key = sha256(f"{project_id}:{action_type}:{target_key}:{generation}")[:32]`

For GitHub Issues created by mini me, the `operation_key` MUST be embedded in the issue body as a deterministic HTML comment marker:
`<!-- minime-opkey: <operation_key> -->`

During issue creation deduplication:
1. Search remote issues by repository binding.
2. Inspect issue body for exact comment marker `<!-- minime-opkey: <operation_key> -->`.
3. Re-use issue (`SUCCESS` / `REUSED_EXISTING`) ONLY if exact `operation_key` comment marker matches.
4. Identical titles without matching `operation_key` marker MUST NOT be reused.

For Pull Requests, the identity is bound to `(repository, head_branch, base_branch, head_sha)`.
For Git Branches, the identity is bound to `(repository, branch_name, candidate_sha)`.

## Delete Remote Branch Fail-Closed Logic

An HTTP 404 response alone MUST NOT automatically evaluate to `SUCCESS`.

`delete_remote_branch` MUST classify outcomes as follows:
- **`SUCCESS` (`EXECUTION_SUCCESS`)**: Remote DELETE request returns HTTP 200 or 204 OK under valid authentication.
- **`SUCCESS` (`ALREADY_ABSENT`)**: Remote DELETE returns 404, AND subsequent `ls-remote` query under valid authorization authoritatively verifies that `refs/heads/<branch>` is absent in the target repository.
- **`FAILURE` (`AUTH_REQUIRED`)**: DELETE or observation query returns HTTP 401 or 403.
- **`UNKNOWN` (`UNOBSERVABLE`)**: DELETE or GET query returns 404/500/timeout BUT repository access or ref identity cannot be authoritatively established.

## Production Writer & Adapter Inventory

### 1. GitHub Adapter (`src/minime/adapters/github.py` & `src/minime/domain/interfaces.py`)

| Method Name | Current Signature / Behavior | Fabricated Success Default | Stage B Fail-Closed Migration |
|---|---|---|---|
| `verify_repository` | returns `tuple[bool, str \| None]` | None, but HTTP 500 raises | Return `ExternalActionResult[bool]`; 401/403 -> `FAILURE` (`AUTH_REQUIRED`), 500/429 -> `UNKNOWN` (`UNOBSERVABLE`) |
| `validate_issue_binding` | returns `tuple[bool, str \| None]` | Raises exception on HTTP error | Return `ExternalActionResult[bool]`; 404 -> `FAILURE` (`NOT_FOUND`), 500/429 -> `UNKNOWN` (`UNOBSERVABLE`) |
| `list_issues` | returns `list[dict]` | Returns empty list `[]` on REST & CLI failure | Return `ExternalActionResult[list[dict]]`; failure/unobservable -> `UNKNOWN` with `retry_safety = SAFE` |
| `list_project_items` | returns `list[dict]` | Returns empty list `[]` on CLI failure | Return `ExternalActionResult[list[dict]]`; failure -> `UNKNOWN` |
| `create_issue` | returns `dict[str, Any]` | Returns `{"number": 1, ...}` fallback double when REST & CLI fail! Title-only dedupe. | Return `ExternalActionResult[dict]`; deduct existing by `operation_key` marker; if timeout/unobservable -> `AMBIGUOUS`; NEVER return fake issue #1 or title-only match |
| `add_issue_to_project` | returns `str \| None` | Returns `f"PVTI_mock_{project_number}"` on CLI error! | Return `ExternalActionResult[str]`; if CLI fails -> `FAILURE`/`UNKNOWN`; NEVER return `PVTI_mock_*` |
| `get_pull_request` | returns `PullRequestLookupResult` | Uses enum lookup result | Return `ExternalActionResult[dict]`; `FOUND_EXACT` -> `SUCCESS`, `NOT_FOUND` -> `FAILURE`, `UNOBSERVABLE` -> `UNKNOWN`, `AMBIGUOUS` -> `AMBIGUOUS` |
| `create_pull_request` | returns `dict[str, Any]` | Raises `RuntimeError` | Return `ExternalActionResult[dict]`; timeout after POST -> `AMBIGUOUS` (re-check GET PR by head/base); existing exact PR -> `SUCCESS` (`REUSED_EXISTING`) |
| `push_branch` | returns `bool` | Raises `RuntimeError` | Return `ExternalActionResult[str]` with pushed commit SHA evidence |
| `get_remote_branch_head` | returns `str \| None` | Returns `None` on missing ref or failure | Return `ExternalActionResult[str]`; branch absent -> `FAILURE` (`NOT_FOUND`), git error -> `UNKNOWN` (`UNOBSERVABLE`) |
| `get_pull_request_details` | returns `dict[str, Any]` | Raises `RuntimeError` on 404 / 400 | Return `ExternalActionResult[dict]`; 404 -> `FAILURE` (`NOT_FOUND`), 500 -> `UNKNOWN` (`UNOBSERVABLE`) |
| `close_issue` | returns `bool` | Returns `True` on 404 or exception! | Return `ExternalActionResult[bool]`; GET issue first: if already closed -> `SUCCESS` (`ALREADY_CLOSED`), 404 -> `FAILURE` (`NOT_FOUND`), exception -> `UNKNOWN`; NEVER return `True` on error |
| `update_project_item_status` | returns `str \| bool` | Returns `True` even if `gh project item-edit` fails! | Return `ExternalActionResult[bool]`; check `res.returncode == 0` -> `SUCCESS`, CLI failure -> `FAILURE`/`UNKNOWN`; NEVER return `True` on error |
| `delete_remote_branch` | returns `bool` | Returns `True` even if DELETE fails or throws! | Return `ExternalActionResult[bool]`; HTTP 200/204 -> `SUCCESS`, 404 + ls-remote absent -> `SUCCESS` (`ALREADY_ABSENT`), unobservable -> `UNKNOWN`; NEVER unconditional 404-success |

### 2. Git Execution Utilities (`src/minime/utils/git.py`, `post_merge_service.py`, `orchestration_service.py`)

- `verify_candidate_ancestry`: Return `ExternalActionResult[bool]`. Explicitly verify that `git fetch origin` succeeded or that local refs are observable. If git command fails due to corrupted ref or missing commit object, report `UNKNOWN` (`UNOBSERVABLE`).
- `push_branch`: Verify `candidate_sha` exists locally, verify remote authorization bundle, check `result.returncode == 0`, and observe remote branch head via `ls-remote` postcondition verification.
- `clean_worktree_and_branches`: Check return codes for `git worktree remove` and `git branch -D`. Report explicit cleanup outcome (`ExternalActionResult[bool]`) rather than swallowing errors with logger warnings.

### 3. OpenSpec Filesystem & CLI Operations (`OpenSpecSyncService`, `OpenSpecArchiveService`, `OpenSpecValidationService`)

- `OpenSpecSyncService`: Commands returning 0 are verified against filesystem postconditions (`spec.md` exists and contains valid `## Requirements` section).
- `OpenSpecArchiveService`: Verify directory relocation postcondition (`openspec/changes/archive/YYYY-MM-DD-<name>` exists and source directory in `openspec/changes/` is absent). If move is partial, return `AMBIGUOUS`.

### 4. Provider & Execution Operations (`DeepSeekAuditorRunner`, `ImplementerRunner`, `CodexProviderService`)

- Process exit code 0 is required BUT NOT sufficient for success.
- Must verify output artifact (e.g. review verdict JSON, patch file, or report file) exists, is non-empty, and is validly parseable.
- If process exits 0 but output artifact is missing or invalid: return `outcome = UNKNOWN`, `reason_code = EVIDENCE_INSUFFICIENT`, triggering `NEEDS_HUMAN` gate in domain callers.

### 5. Deployment & Service Operations (`deploy_update.sh`, `ContainerPreviewService`)

- Distinguish `DEPLOY_ACTION_SUCCESS` (deployment script executed with exit code 0) from `PRODUCTION_VERIFIED` (HTTP health check endpoint returned 200 OK with expected version/SHA payload).
- If deploy script returns 0 but health check endpoint is unreachable or times out: report `action_outcome = SUCCESS`, `production_verification = UNKNOWN`, `reason_code = POSTCONDITION_NOT_PROVEN`.

## Extension of `OrchestrationExternalAction` & State Machine Transitions

`ExternalActionType` in `src/minime/domain/enums.py` is extended:

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

State machine transitions for `OrchestrationExternalAction`:
- `RESERVED` -> `EXECUTING`
- `EXECUTING` -> `COMPLETED` (when `ExternalOutcome.SUCCESS`)
- `EXECUTING` -> `FAILED` (when `ExternalOutcome.FAILURE`)
- `EXECUTING` -> `UNKNOWN` (when `ExternalOutcome.UNKNOWN`)
- `EXECUTING` -> `AMBIGUOUS` (when `ExternalOutcome.AMBIGUOUS`)
- `UNKNOWN` / `AMBIGUOUS` -> `EXECUTING` ONLY after observe-before-repeat protocol proves `retry_safety == RetrySafety.SAFE`.
- `UNKNOWN` / `AMBIGUOUS` -> `COMPLETED` when observe-before-repeat protocol authoritatively proves postcondition was achieved.
- `FAILED` MUST NOT automatically retry unless a domain caller explicitly authorizes a retry according to policy.

## PostMerge Fail-Closed Contract

In Stage B, `PostMergeService` is updated to consume `ExternalActionResult[T]` for all external operations:
- **Historical Evidence vs Current State**: Stored `COMPLETED` action records in `OrchestrationExternalAction` prevent duplicate mutation commands. However, when reconciliation requires verifying current closure postconditions (e.g. issue closure, branch absence, sync spec presence), `PostMergeService` MUST query current remote external truth via `GitHubAdapter` and Git utilities.
- **Fail-Closed Reporting**: If issue closure or project item update returns `UNKNOWN` or `FAILURE`, `PostMergeService` records the failure in `PostMergeReconciliationResult` and DOES NOT fabricate all phase booleans as `True`.
- **No Direct Lifecycle Writes**: PostMerge completions route strictly through `LifecycleTransitionAuthority` (Stage A).

## Test Strategy

- **Isolated Test Fixtures**: All fake/stub adapters (e.g. `ReadinessGitHubStub`) will be strictly scoped to `tests/conftest.py` and test modules.
- **Adversarial Unit Tests**:
  - Test `GitHubAdapter.create_issue` timeout -> returns `AMBIGUOUS`, zero fake issue #1, zero title-only dedupe.
  - Test `GitHubAdapter.close_issue` on 404 -> returns `FAILURE` (`NOT_FOUND`), zero `True` return.
  - Test `GitHubAdapter.add_issue_to_project` CLI failure -> returns `FAILURE`/`UNKNOWN`, zero `PVTI_mock_*` ID.
  - Test `GitHubAdapter.delete_remote_branch` 404 without repository verification -> returns `UNKNOWN`/`FAILURE`.
  - Test `GitHubAdapter.delete_remote_branch` 404 + ls-remote absent -> returns `SUCCESS` (`ALREADY_ABSENT`).
  - Test `create_pull_request` when exact PR already exists -> returns `SUCCESS` (`REUSED_EXISTING`).
  - Test Git ancestry on corrupted ref -> returns `UNKNOWN` (`UNOBSERVABLE`).
  - Test Provider execution exit 0 with missing output file -> returns `UNKNOWN` (`EVIDENCE_INSUFFICIENT`).
  - Test Deployment action exit 0 with unreachable health check -> returns `SUCCESS` action with `PRODUCTION_VERIFIED = UNKNOWN`.
  - Test observe-before-repeat after `AMBIGUOUS`: when absence is inconclusive or `retry_safety == UNKNOWN`, verify automatic repeat is strictly BLOCKED.
