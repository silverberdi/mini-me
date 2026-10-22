"""Regression coverage for repository identity normalization used by F2."""

import pytest

from minime.services.project_service import normalize_repository_identity


def test_normalize_repository_identity():
    assert normalize_repository_identity("owner/repo") == "owner/repo"
    assert normalize_repository_identity("https://github.com/owner/repo.git") == "owner/repo"
    assert normalize_repository_identity("https://github.com/owner/repo") == "owner/repo"
    assert normalize_repository_identity("git@github.com:owner/repo.git") == "owner/repo"
    assert normalize_repository_identity("ssh://git@github.com/owner/repo.git") == "owner/repo"
    assert normalize_repository_identity("github.com/owner/repo") == "owner/repo"
    assert (
        normalize_repository_identity("https://gitlab.example.com/owner/repo.git")
        == "gitlab.example.com/owner/repo"
    )
    assert normalize_repository_identity("https://gitlab.example.com/owner/repo.git") != "owner/repo"
    assert normalize_repository_identity("/var/repos/local-repo") == "/var/repos/local-repo"

    with pytest.raises(ValueError, match="cannot be empty"):
        normalize_repository_identity("")
