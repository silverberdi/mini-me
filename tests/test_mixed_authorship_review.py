import json
from pathlib import Path

from minime.domain.models import CandidateAuthorship, CheckResult, Project
from minime.services.authorship_service import AuthorshipService
from minime.services.reviewer_contract import build_reviewer_prompt


def _authorship(role: str, files: list[str], attempt: int) -> CandidateAuthorship:
    return CandidateAuthorship(
        job_id="job-1", agent_role=role, model_identity=f"{role}-model",
        attempt_number=attempt, files_touched=files,
    )


def test_reviewer_authorship_only_counts_surviving_current_candidate(in_memory_uow):
    uow = in_memory_uow
    uow.candidate_authorships.save(_authorship("codex", ["src/kept.py"], 1))
    uow.candidate_authorships.save(_authorship("antigravity", ["src/kept.py", "src/discarded.py"], 2))

    evidence = AuthorshipService().evaluate_reviewer_authorship(
        "job-1", "antigravity", ["src/kept.py"], "candidate-sha", 3, uow,
    )

    assert evidence["is_mixed_authorship"] is True
    assert evidence["surviving_contributions"][0]["files"] == ["src/kept.py"]


def test_discarded_historical_attempt_does_not_trigger_mixed_authorship(in_memory_uow):
    in_memory_uow.candidate_authorships.save(_authorship("antigravity", ["src/discarded.py"], 2))
    evidence = AuthorshipService().evaluate_reviewer_authorship(
        "job-1", "antigravity", ["src/implementer.py"], "candidate-sha", 2, in_memory_uow,
    )
    assert evidence["is_mixed_authorship"] is False
    assert evidence["surviving_contributions"] == []


def test_no_reassignment_prompt_defaults_to_single_authorship(tmp_path: Path):
    project = Project(project_id="p1", display_name="P", repository="o/r")
    change = tmp_path / "openspec" / "changes" / "change"
    (change / "specs").mkdir(parents=True)
    for name, content in (("proposal.md", "# Proposal"), ("tasks.md", "# Tasks"), ("design.md", "# Design")):
        (change / name).write_text(content)
    prompt = build_reviewer_prompt(
        project, "change", "job-1", "candidate", "base", tmp_path, [
            CheckResult(job_id="job-1", check_name="tests", command="pytest", exit_code=0, duration_ms=1, output_snippet="ok")
        ],
    )
    payload_text = prompt.split("### REVIEW CONTEXT PAYLOAD ###\n", 1)[1]
    payload = json.JSONDecoder().raw_decode(payload_text)[0]
    assert payload["authorship"]["is_mixed_authorship"] is False
