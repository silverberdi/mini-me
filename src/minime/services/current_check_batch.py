"""Shared validation for the newest complete deterministic-check batch."""

from __future__ import annotations

from minime.domain.models import CheckResult, Job, OrchestrationRun, Project


def validate_current_checks_batch(
    *,
    check_results: list[CheckResult],
    job: Job,
    run: OrchestrationRun,
    project: Project | None,
    require_configured_checks: bool = False,
) -> tuple[bool, str | None, list[CheckResult]]:
    """Return the latest exact configured batch, never an arbitrary passing row.

    Ordinary orchestration retains its existing behavior when a project has no
    configured checks. Exceptional frozen-candidate review passes
    ``require_configured_checks=True`` and therefore fails closed on an empty
    configuration.
    """
    expected_checks = [
        check
        for check in (project.checks if project else [])
        if isinstance(check, dict) and check.get("name")
    ]
    if not expected_checks:
        if require_configured_checks:
            return False, "No configured deterministic checks for exceptional review.", []
        return True, None, []

    count = len(expected_checks)
    eligible = [
        result
        for result in check_results
        if result.candidate_sha == job.candidate_sha
        and result.candidate_generation == run.current_generation
    ]
    if len(eligible) < count:
        return False, "Insufficient check results for the current candidate.", []

    ordered = sorted(eligible, key=lambda item: (item.created_at, item.result_id), reverse=True)
    batch = ordered[:count]
    names = [item["name"] for item in expected_checks]
    commands = {item["name"]: str(item.get("command") or "") for item in expected_checks}
    batch_names = [item.check_name for item in batch]
    if len(set(batch_names)) != count or set(batch_names) != set(names):
        return False, "Latest check batch is duplicate, incomplete, or unexpected.", []
    if any(item.command != commands.get(item.check_name, "") for item in batch):
        return False, "Latest check batch command does not match project configuration.", []

    min_timestamp = min(item.created_at for item in batch)
    max_timestamp = max(item.created_at for item in batch)
    total_duration = sum(item.duration_ms for item in batch) / 1000.0
    allowed_spread = max(60.0, total_duration + 60.0)
    if (max_timestamp - min_timestamp).total_seconds() > allowed_spread:
        return False, "Latest check batch exceeds the allowed time window.", []
    if any(item.exit_code != 0 for item in batch):
        return False, "Latest complete check batch contains a failure.", batch
    return True, None, batch
