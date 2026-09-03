# Spec: PR Preparation and Recovery

## Requirement: Native PR Creation and Recovery
The orchestration service SHALL natively prepare and adopt GitHub Pull Requests for audited candidate SHAs, linking the canonical GitHub Issue and preventing duplicate or contradictory branch pushes.

### Scenarios

#### Scenario: Idempotent Remote Branch Push
- GIVEN an audited candidate SHA,
- WHEN `PREPARING_PR` inspects the remote branch head,
- THEN IF the remote branch head already matches the candidate SHA, `mini me` SHALL mark the push action COMPLETED without issuing a redundant `git push`.
- THEN IF the remote branch does not exist, `mini me` SHALL push the candidate SHA to `refs/heads/minime/<change_name>`.
- THEN IF the remote branch exists with a different SHA, `mini me` SHALL fail closed to `NEEDS_HUMAN` to protect remote branch integrity.

#### Scenario: Pull Request Creation and Adoption
- GIVEN a pushed remote branch,
- WHEN `PREPARING_PR` evaluates pull request state on GitHub,
- THEN IF an open PR exists matching the branch and base, `mini me` SHALL adopt the PR, bind its number and URL to `ProjectBinding`, and mark the action COMPLETED.
- THEN IF no PR exists, `mini me` SHALL create a new PR linking `Closes #<issue_number>` and bind its number and URL to `ProjectBinding`.
