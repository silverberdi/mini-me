import io
import stat
import zipfile

import pytest

from minime.services.context_archive import ContextArchiveExtractor, UnsafeContextArchive


def _zip(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name)
            if mode is not None:
                info.external_attr = mode << 16
            archive.writestr(info, data)
    return output.getvalue()


def test_extracts_regular_context_files_with_hash_and_restrictive_mode(tmp_path):
    package = _zip([("docs/requirements.md", b"must preserve this", stat.S_IFREG | 0o644)])
    result = ContextArchiveExtractor().extract(package, tmp_path / "extracted")

    file_path = tmp_path / "extracted/docs/requirements.md"
    assert file_path.read_bytes() == b"must preserve this"
    assert stat.S_IMODE(file_path.stat().st_mode) == 0o600
    assert result.files == ("docs/requirements.md",)
    assert len(result.sha256) == 64


@pytest.mark.parametrize(
    "entry,reason",
    [
        (("../escape.txt", b"bad", stat.S_IFREG | 0o600), "traversal"),
        (("tool.sh", b"echo bad", stat.S_IFREG | 0o755), "executable"),
        (("secrets.pem", b"-----BEGIN PRIVATE KEY-----", stat.S_IFREG | 0o600), "secret"),
        (("link", b"target", stat.S_IFLNK | 0o777), "links"),
    ],
)
def test_rejects_unsafe_context_entries_before_extraction(tmp_path, entry, reason):
    package = _zip([entry])
    target = tmp_path / "extracted"

    with pytest.raises(UnsafeContextArchive, match=reason):
        ContextArchiveExtractor().extract(package, target)

    assert not list(target.rglob("*")) if target.exists() else True


def test_rejects_case_colliding_paths(tmp_path):
    package = _zip(
        [
            ("docs/Readme.md", b"one", stat.S_IFREG | 0o600),
            ("docs/readme.md", b"two", stat.S_IFREG | 0o600),
        ]
    )
    with pytest.raises(UnsafeContextArchive, match="colliding"):
        ContextArchiveExtractor().extract(package, tmp_path / "extracted")


def test_rejects_late_secret_before_writing_any_archive_entries(tmp_path):
    package = _zip(
        [
            ("docs/valid.md", b"safe", stat.S_IFREG | 0o600),
            (
                "docs/secret.md",
                b"-----BEGIN PRIVATE KEY-----",
                stat.S_IFREG | 0o600,
            ),
        ]
    )
    target = tmp_path / "extracted"

    with pytest.raises(UnsafeContextArchive, match="secret material"):
        ContextArchiveExtractor().extract(package, target)

    assert list(target.iterdir()) == []
