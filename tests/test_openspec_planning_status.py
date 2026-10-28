"""Planning completeness comes from OpenSpec, never file-name heuristics."""

import json
import subprocess
from pathlib import Path

from minime.adapters.openspec import OpenSpecAdapter


def test_official_openspec_complete_status(monkeypatch, tmp_path: Path):
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(
            cmd, 0,
            stdout=json.dumps({
                "isPlanningComplete": True,
                "artifacts": [
                    {"id": "proposal", "status": "done"},
                    {"id": "specs", "status": "done"},
                    {"id": "design", "status": "done"},
                    {"id": "tasks", "status": "done"},
                ],
            }),
            stderr="",
        )

    monkeypatch.setattr("minime.adapters.openspec.subprocess.run", run)
    status = OpenSpecAdapter().planning_status("example-change", tmp_path)
    assert status["status"] == "PASS"
    assert status["pending"] == []
    assert calls[0][0] == [
        "openspec", "status", "--change", "example-change", "--json"
    ]
    assert calls[0][1]["cwd"] == str(tmp_path)


def test_official_openspec_reports_pending_artifacts(monkeypatch, tmp_path: Path):
    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 0,
            stdout=json.dumps({
                "isPlanningComplete": False,
                "artifacts": [
                    {"id": "proposal", "status": "done"},
                    {"id": "design", "status": "ready"},
                    {"id": "tasks", "status": "blocked"},
                ],
            }),
            stderr="",
        )

    monkeypatch.setattr("minime.adapters.openspec.subprocess.run", run)
    result = OpenSpecAdapter().planning_status("example-change", tmp_path)
    assert result["status"] == "INCOMPLETE"
    assert result["pending"] == ["design", "tasks"]


def test_missing_or_ambiguous_openspec_status_fails_closed(monkeypatch, tmp_path: Path):
    for body in ("", "{bad", '{"artifacts":[]}', '{"isPlanningComplete":"true"}'):
        def run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout=body, stderr="")

        monkeypatch.setattr("minime.adapters.openspec.subprocess.run", run)
        assert OpenSpecAdapter().planning_status("example-change", tmp_path)["status"] == "UNKNOWN"
