## 1. Terminal-aware run projection

- [x] 1.1 Guard the existing `is_human_required` calculation in `list_orchestration_runs` so terminal outcome or completed stage always makes it false, preserving all non-terminal projection behavior.

## 2. Regression coverage

- [x] 2.1 Add focused endpoint regression coverage for `COMPLETED`, `FAILED`, `CANCELLED`, and `current_stage=COMPLETED` with stale human-gate data; assert terminal runs are not projected as `HUMAN_REQUIRED`, and existing non-terminal human-gate tests remain green.
