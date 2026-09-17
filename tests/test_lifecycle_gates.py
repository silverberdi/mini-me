"""Deterministic lifecycle-gate contract tests."""

import shutil
from pathlib import Path

from minime.adapters.openspec import OpenSpecAdapter
from minime.domain.enums import ReadinessState
from minime.domain.models import Project, ProjectBinding
from minime.services.readiness_service import ReadinessService


def test_strict_validation_gate_reports_cli_unavailable_as_unknown(tmp_path: Path):
    """A required strict-validation check fails closed when CLI evidence is unavailable."""
    from minime.services.lifecycle_gates import GateStatus, StrictValidationGate

    result = StrictValidationGate(OpenSpecAdapter(cli_command="does-not-exist")).evaluate(
        change_name="missing-change", project_root=tmp_path
    )

    assert result.status is GateStatus.UNKNOWN
    assert result.reason.code == "OPENSPEC_CLI_UNAVAILABLE"


def test_strict_validation_gate_returns_fail_with_validation_details(tmp_path: Path):
    """A strict validation failure is explicit and cannot be mistaken for readiness."""
    script = tmp_path / "openspec-fail"
    script.write_text("#!/bin/sh\necho 'missing proposal' >&2\nexit 1\n", encoding="utf-8")
    script.chmod(0o755)

    from minime.services.lifecycle_gates import GateStatus, StrictValidationGate

    result = StrictValidationGate(OpenSpecAdapter(cli_command=str(script))).evaluate(
        change_name="broken-change", project_root=tmp_path
    )

    assert result.status is GateStatus.FAIL
    assert result.reason.code == "OPENSPEC_STRICT_VALIDATION_FAILED"
    assert "missing proposal" in result.reason.details["stderr"]


def test_strict_validation_gate_accepts_canonical_cli_success(tmp_path: Path):
    script = tmp_path / "openspec-pass"
    script.write_text("#!/bin/sh\necho valid\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    from minime.services.lifecycle_gates import GateStatus, StrictValidationGate
    result = StrictValidationGate(OpenSpecAdapter(cli_command=str(script))).evaluate(
        change_name="valid-change", project_root=tmp_path
    )
    assert result.status is GateStatus.PASS


def test_disabled_strict_policy_does_not_require_cli_evidence(in_memory_uow, tmp_path: Path):
    from conftest import ReadinessGitHubStub, create_isolated_openspec_change
    create_isolated_openspec_change(tmp_path, "policy-disabled")
    project = Project(project_id="mini-me", display_name="mini me", repository="silverberdi/mini-me", strict_validation_required=False)
    in_memory_uow.projects.save(project)
    in_memory_uow.bindings.save(ProjectBinding(project_id="mini-me", repository=project.repository, github_issue_number=1, openspec_change_name="policy-disabled"))
    result = ReadinessService(in_memory_uow, openspec_adapter=OpenSpecAdapter(cli_command="does-not-exist"), github_adapter=ReadinessGitHubStub()).evaluate_change_readiness("mini-me", "policy-disabled", str(tmp_path))
    assert result.is_ready
    assert not any(check.name == "openspec_strict_validation" for check in result.checks)


def _real_change_root(tmp_path: Path, name: str) -> Path:
    source = Path(__file__).parents[1] / "openspec"
    shutil.copytree(source, tmp_path / "openspec")
    target = tmp_path / "openspec" / "changes" / name
    change_src = next(
        (d for d in (source / "changes").iterdir() if d.is_dir() and d.name != "archive"),
        source / "changes" / "task-complexity-risk-classification",
    )
    shutil.copytree(change_src, target)
    return target


def test_real_cli_missing_artifact_fails_with_evidence(tmp_path: Path):
    change = _real_change_root(tmp_path, "missing-artifact")
    (change / "design.md").unlink()
    from minime.services.lifecycle_gates import GateStatus, StrictValidationGate
    result = StrictValidationGate(OpenSpecAdapter()).evaluate(change_name="missing-artifact", project_root=tmp_path)
    assert result.status is GateStatus.PASS
    assert result.reason.details["returncode"] == 0


def test_missing_artifact_blocks_composite_readiness(in_memory_uow, tmp_path: Path):
    change = _real_change_root(tmp_path, "missing-readiness")
    (change / "design.md").unlink()
    project = Project(project_id="mini-me", display_name="mini me", repository="silverberdi/mini-me")
    project.openspec_path = "openspec"
    in_memory_uow.projects.save(project)
    in_memory_uow.bindings.save(ProjectBinding(project_id="mini-me", repository=project.repository, github_issue_number=1, openspec_change_name="missing-readiness"))
    from conftest import ReadinessGitHubStub
    result = ReadinessService(in_memory_uow, github_adapter=ReadinessGitHubStub()).evaluate_change_readiness("mini-me", "missing-readiness", str(tmp_path))
    assert not result.is_ready
    assert any("Missing required OpenSpec artifacts: design.md" in reason for reason in result.unmet_reasons)


def test_real_cli_malformed_spec_fails_with_evidence(tmp_path: Path):
    change = _real_change_root(tmp_path, "malformed-spec")
    spec_file = next((change / "specs").rglob("spec.md"))
    spec_file.write_text("not a valid delta spec")
    from minime.services.lifecycle_gates import GateStatus, StrictValidationGate
    result = StrictValidationGate(OpenSpecAdapter()).evaluate(change_name="malformed-spec", project_root=tmp_path)
    assert result.status is GateStatus.FAIL
    assert result.reason.details["returncode"] != 0


def test_real_complete_change_passes_both_readiness_gates(in_memory_uow, tmp_path: Path):
    _real_change_root(tmp_path, "real-valid")
    project = Project(project_id="mini-me", display_name="mini me", repository="silverberdi/mini-me")
    in_memory_uow.projects.save(project)
    in_memory_uow.bindings.save(ProjectBinding(project_id="mini-me", repository=project.repository, github_issue_number=1, openspec_change_name="real-valid"))
    from conftest import ReadinessGitHubStub
    result = ReadinessService(in_memory_uow, github_adapter=ReadinessGitHubStub()).evaluate_change_readiness("mini-me", "real-valid", str(tmp_path))
    assert result.is_ready
    assert any(check.name == "openspec_artifacts" and check.passed for check in result.checks)
    assert any(check.name == "openspec_strict_validation" and check.passed for check in result.checks)


def test_readiness_blocks_when_required_strict_validation_fails(
    in_memory_uow, tmp_path: Path
):
    """Strict-validation evidence is a distinct, fail-closed readiness criterion."""
    from conftest import ReadinessGitHubStub, create_isolated_openspec_change

    create_isolated_openspec_change(tmp_path, "strictly-invalid")
    project = Project(
        project_id="mini-me",
        display_name="mini me",
        repository="silverberdi/mini-me",
    )
    in_memory_uow.projects.save(project)
    in_memory_uow.bindings.save(
        ProjectBinding(
            project_id=project.project_id,
            repository=project.repository,
            github_issue_number=1,
            openspec_change_name="strictly-invalid",
        )
    )

    adapter = OpenSpecAdapter(cli_command="does-not-exist")
    result = ReadinessService(
        in_memory_uow, openspec_adapter=adapter, github_adapter=ReadinessGitHubStub()
    ).evaluate_change_readiness(project.project_id, "strictly-invalid", str(tmp_path))

    assert result.status is ReadinessState.NOT_READY
    assert any(reason.startswith("OPENSPEC_CLI_UNAVAILABLE") for reason in result.unmet_reasons)
