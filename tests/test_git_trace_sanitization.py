import subprocess

from minime.adapters import github as github_module


def test_authenticated_git_subprocess_strips_trace_environment(monkeypatch, tmp_path):
    values = {
        "GIT_TRACE": "1",
        "GIT_TRACE_PACKET": "1",
        "GIT_TRACE_CURL": "1",
        "GIT_CURL_VERBOSE": "1",
        "GIT_TRANSPORT_TRACE": "1",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    captured = {}

    def run(*args, **kwargs):
        captured.update(kwargs["env"])
        return subprocess.CompletedProcess(args[0], 0, stdout="", stderr="")

    monkeypatch.setattr(github_module.subprocess, "run", run)
    github_module.GitHubAdapter._run_git(
        ["git", "ls-remote"], cwd=tmp_path, timeout=1, secrets=["token"]
    )
    assert all(key not in captured for key in values)
