# mini me — review active candidate (POST-APPLY Quality Hook)

Use `minime-reviewer` plus canonical/repository/provider/evidence guards. Start read-only. Review the exact candidate against active OpenSpec artifacts and check evidence. Return structured findings. Do not fix code while acting as reviewer.

## Review Protocol & Quality Hook Gate

1. **Preconditions & Independence Verification**:
   - Verify `implementer_model_identity != reviewer_model_identity`.
   - Ensure the reviewer is not the same primary agent that implemented the candidate.
   - Verify candidate SHA is committed and unchanged.

2. **Dynamic Specialty Coverage**:
   - Run specialty selector:
     ```bash
     python -m minime.quality_hooks.cli select-specialties $(git diff --name-only origin/main...HEAD | sed 's/^/-f /')
     ```
   - Cover all required specialties (`security_auth`, `data_migrations`, `reliability_recovery`, `tests_coverage`, `operational_delivery`, or `general_architecture`).
   - If any required specialty is not covered or reviewed, verdict is `BLOCKED`.

3. **Diff-to-Spec & Failure Path Audit**:
   - Validate observable specs against concrete diff.
   - Scan diff for fail-closed regressions (e.g. PR #139 auth failure swallowing, secret leakage in exceptions).
   - Ensure negative/denial branches and failure recovery paths are explicitly handled and tested.

4. **Hook Evaluation & Report**:
   - Run POST-APPLY evaluation:
     ```bash
     python -m minime.quality_hooks.cli evaluate-post-apply --change "<name>" --base-sha "<base>" --candidate-sha "<cand>" --implementer-model "<impl_model>" --reviewer-model "<rev_model>"
     ```
   - Findings must conform to `schemas/quality-hook-report.schema.json`.
   - Any unresolved `CRITICAL` or `HIGH` finding produces a `FAIL` verdict.
