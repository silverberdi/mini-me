"""Deterministic F2 taxonomy and document-index tests; no model calls."""

import io
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from minime.adapters.openspec import OpenSpecAdapter
from minime.domain.enums import ExternalOutcome
from minime.services.context_archive import ContextArchiveExtractor
from minime.services.greenfield_bootstrap import (
    GreenfieldBootstrapCoordinator,
    GreenfieldBootstrapError,
)
from minime.services.project_context_catalog import (
    CONTEXT_DOCUMENT_CATALOG,
    CONTEXT_DOCUMENT_PATHS,
    CONTEXT_ROOT_INDEX,
    catalog_instruction,
    generated_context_path_allowed,
    populated_catalog_documents,
)


def _workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "repo"
    package = tmp_path / "package"
    sha = "a" * 64
    incoming = root / "context" / "incoming" / sha
    incoming.mkdir(parents=True)
    package.mkdir()
    for name, value in (
        ("business.md", "Intent: help teams understand files."),
        ("planning.md", "Existing roadmap and historical backlog."),
    ):
        (package / name).write_text(value, encoding="utf-8")
        (incoming / name).write_text(value, encoding="utf-8")
    (root / "openspec").mkdir()
    (root / "AGENTS.md").write_text(
        "Project context: context/INDEX.md", encoding="utf-8"
    )
    (root / "openspec" / "config.yaml").write_text(
        "schema: spec-driven\ncontext: context/INDEX.md\n", encoding="utf-8"
    )
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-m", "base"], cwd=root, check=True, capture_output=True
    )
    return root, package, incoming


def _fill(root: Path) -> None:
    texts = {
        "01-negocio/intencion-de-negocio.md": (
            "# Intencion\nHelp teams understand files.\n"
            "Source: ../incoming/" + "a" * 64 + "/business.md\n"
        ),
        "02-producto/funcionalidades.md": (
            "# Funcionalidad documentada\nUnderstand files.\n"
            "Source: ../incoming/" + "a" * 64 + "/business.md\n"
        ),
        "12-planificacion/roadmap-documentado.md": (
            "# Roadmap recibido\nHistorical roadmap only; not executable.\n"
            "Source: ../incoming/" + "a" * 64 + "/planning.md\n"
        ),
        "12-planificacion/antecedentes-de-planificacion.md": (
            "# Backlog historico\nHistorical reference only; no tasks are authorized.\n"
            "Source: ../incoming/" + "a" * 64 + "/planning.md\n"
        ),
    }
    for relative, contents in texts.items():
        path = root / "context" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    empty = root / "context" / "08-seguridad" / "cifrado.md"
    empty.parent.mkdir(parents=True, exist_ok=True)
    empty.write_text("", encoding="utf-8")
    (root / CONTEXT_ROOT_INDEX).write_text(
        "# Proyecto\n"
        + "\n".join(
            f"- [{name}]({name})"
            for name in texts
        )
        + "\nSources: business.md, planning.md "
        + "context/incoming/" + "a" * 64 + "/business.md; "
        + "context/incoming/" + "a" * 64 + "/planning.md\n",
        encoding="utf-8",
    )


def test_standard_taxonomy_has_stable_nonempty_sections_and_no_operational_backlog():
    assert len(CONTEXT_DOCUMENT_CATALOG) == 20
    assert len(CONTEXT_DOCUMENT_PATHS) == 204
    assert "context/01-negocio/intencion-de-negocio.md" in CONTEXT_DOCUMENT_PATHS
    assert "context/12-planificacion/roadmap-documentado.md" in CONTEXT_DOCUMENT_PATHS
    assert "context/12-planificacion/antecedentes-de-planificacion.md" in CONTEXT_DOCUMENT_PATHS
    assert "context/backlog.md" not in CONTEXT_DOCUMENT_PATHS
    assert "context/12-planificacion/backlog.md" not in CONTEXT_DOCUMENT_PATHS
    assert len(CONTEXT_DOCUMENT_PATHS) == len(set(CONTEXT_DOCUMENT_PATHS))
    assert "12-planificacion/" in catalog_instruction()


def test_organizer_contract_distributes_sources_without_new_business_inference():
    prompt = GreenfieldBootstrapCoordinator.THINKING_AGENT_INSTRUCTION
    assert "MULTIPLE" in prompt
    assert "roadmap-documentado.md" in prompt
    assert "operational backlog" in prompt
    assert "ONLY substantively populated" in prompt
    assert "no" in prompt.lower()
    assert "OpenSpec proposals/specs/tasks" in prompt


def test_generated_file_scope_only_accepts_canonical_docs_and_originals():
    assert generated_context_path_allowed("context/00-general/descripcion-del-proyecto.md")
    assert generated_context_path_allowed("context/15-diseno-y-recursos/identidad-de-marca.md")
    assert generated_context_path_allowed("context/incoming/" + "a" * 64 + "/diagram.png")
    assert generated_context_path_allowed(CONTEXT_ROOT_INDEX)
    assert not generated_context_path_allowed("context/backlog.md")
    assert not generated_context_path_allowed("context/12-planificacion/new-backlog.md")
    assert not generated_context_path_allowed("src/main.py")


def test_populated_documents_are_indexed_and_empty_documents_are_omitted(tmp_path):
    root, package, incoming = _workspace(tmp_path)
    _fill(root)
    populated = populated_catalog_documents(root)
    assert "context/01-negocio/intencion-de-negocio.md" in populated
    assert "context/02-producto/funcionalidades.md" in populated
    assert "context/12-planificacion/roadmap-documentado.md" in populated
    assert "context/08-seguridad/cifrado.md" not in populated
    GreenfieldBootstrapCoordinator._validate_candidate(
        root, incoming, ("business.md", "planning.md"), package
    )


def test_an_empty_document_must_not_appear_in_main_index(tmp_path):
    root, package, incoming = _workspace(tmp_path)
    _fill(root)
    index = root / CONTEXT_ROOT_INDEX
    index.write_text(
        index.read_text(encoding="utf-8")
        + "\n[Not documented](08-seguridad/cifrado.md)\n",
        encoding="utf-8",
    )
    with pytest.raises(GreenfieldBootstrapError, match="empty canonical"):
        GreenfieldBootstrapCoordinator._validate_candidate(
            root, incoming, ("business.md", "planning.md"), package
        )


def test_populated_file_missing_from_index_blocks_publication(tmp_path):
    root, package, incoming = _workspace(tmp_path)
    _fill(root)
    index = root / CONTEXT_ROOT_INDEX
    index.write_text(
        index.read_text(encoding="utf-8").replace(
            "- [12-planificacion/roadmap-documentado.md]"
            "(12-planificacion/roadmap-documentado.md)", ""
        ),
        encoding="utf-8",
    )
    with pytest.raises(GreenfieldBootstrapError, match="absent from the main index"):
        GreenfieldBootstrapCoordinator._validate_candidate(
            root, incoming, ("business.md", "planning.md"), package
        )


def test_agent_cannot_create_a_nonstandard_generated_backlog(tmp_path):
    root, _, _ = _workspace(tmp_path)
    candidate = root / "context" / "backlog.md"
    candidate.write_text("# Unauthorized new backlog", encoding="utf-8")
    with pytest.raises(GreenfieldBootstrapError, match="unrelated"):
        GreenfieldBootstrapCoordinator._validate_candidate_scope(root)


def test_heading_only_placeholder_is_not_a_populated_document(tmp_path):
    root, package, incoming = _workspace(tmp_path)
    _fill(root)
    placeholder = root / "context" / "08-seguridad" / "cifrado.md"
    placeholder.write_text("# Cifrado\n\n## Detalles pendientes\n", encoding="utf-8")
    assert "context/08-seguridad/cifrado.md" not in populated_catalog_documents(root)
    GreenfieldBootstrapCoordinator._validate_candidate(
        root, incoming, ("business.md", "planning.md"), package
    )
    index = root / CONTEXT_ROOT_INDEX
    index.write_text(
        index.read_text(encoding="utf-8")
        + "\n[Cifrado](08-seguridad/cifrado.md)\n",
        encoding="utf-8",
    )
    with pytest.raises(GreenfieldBootstrapError, match="empty canonical"):
        GreenfieldBootstrapCoordinator._validate_candidate(
            root, incoming, ("business.md", "planning.md"), package
        )


def test_thinking_agent_must_not_add_files_to_original_zip_revision(tmp_path):
    root, package, incoming = _workspace(tmp_path)
    _fill(root)
    (incoming / "invented.md").write_text("not from ZIP", encoding="utf-8")
    with pytest.raises(GreenfieldBootstrapError, match="source inventory"):
        GreenfieldBootstrapCoordinator._validate_candidate(
            root, incoming, ("business.md", "planning.md"), package
        )


def test_deterministic_greenfield_and_incremental_documentary_journeys(tmp_path: Path):
    """Exercise ZIP/OpenSpec/document/PR boundaries with doubles, never a model."""

    def git(*args: str, cwd: Path) -> str:
        result = subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
        )
        return result.stdout.strip()

    def make_archive(files: dict[str, str]) -> bytes:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as package:
            for name, value in files.items():
                package.writestr(name, value)
        return stream.getvalue()

    def populate(worktree: Path, source_sha: str, source_files: tuple[str, ...], *, incremental: bool):
        source_lines = "\n".join(
            f"- {relative}: context/incoming/{source_sha}/{relative}"
            for relative in source_files
        )
        (worktree / "AGENTS.md").write_text(
            "Existing instructions preserved.\nContext: context/INDEX.md\n",
            encoding="utf-8",
        )
        config = worktree / "openspec" / "config.yaml"
        config.write_text(
            config.read_text(encoding="utf-8") + "\ncontext: context/INDEX.md\n",
            encoding="utf-8",
        )
        if incremental:
            document = worktree / "context/12-planificacion/roadmap-documentado.md"
            document.parent.mkdir(parents=True, exist_ok=True)
            document.write_text(
                document.read_text(encoding="utf-8") if document.exists() else "# Roadmap recibido\n",
                encoding="utf-8",
            )
            with document.open("a", encoding="utf-8") as stream:
                stream.write("\nNueva fuente documental; no es una instrucción operativa.\n")
            index = worktree / "context/INDEX.md"
            with index.open("a", encoding="utf-8") as stream:
                stream.write(
                    "\n- [12-planificacion/roadmap-documentado.md]"
                    "(12-planificacion/roadmap-documentado.md)\n"
                    f"\n{source_lines}\n"
                )
        else:
            document = worktree / "context/01-negocio/intencion-de-negocio.md"
            document.parent.mkdir(parents=True, exist_ok=True)
            document.write_text(
                "# Intención de negocio\nEquipos entienden sus archivos.\n"
                f"Source: context/incoming/{source_sha}/{source_files[0]}\n",
                encoding="utf-8",
            )
            index = worktree / "context/INDEX.md"
            index.parent.mkdir(parents=True, exist_ok=True)
            index.write_text(
                "# Contexto\n\n"
                "- [01-negocio/intencion-de-negocio.md]"
                "(01-negocio/intencion-de-negocio.md)\n\n"
                f"{source_lines}\n",
                encoding="utf-8",
            )

    class RecordingPrAdapter:
        def __init__(self):
            self.prs: list[dict[str, str]] = []

        def push_branch(self, worktree: Path, remote: str, branch: str, head_sha: str):
            subprocess.run(
                ["git", "push", remote, branch], cwd=worktree, check=True, capture_output=True
            )
            return SimpleNamespace(outcome=ExternalOutcome.SUCCESS, data=head_sha)

        def create_pr(self, branch: str, base: str, head_sha: str):
            self.prs.append({"branch": branch, "base": base, "head_sha": head_sha})

    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    repo.mkdir()
    git("init", "-b", "main", cwd=repo)
    git("config", "user.email", "test@example.com", cwd=repo)
    git("config", "user.name", "Test", cwd=repo)
    (repo / "README.md").write_text("# fixture\n", encoding="utf-8")
    git("add", ".", cwd=repo)
    git("commit", "-m", "base", cwd=repo)
    git("remote", "add", "origin", str(remote), cwd=repo)
    git("push", "-u", "origin", "main", cwd=repo)
    base_sha = git("rev-parse", "HEAD", cwd=repo)

    extractor = ContextArchiveExtractor()
    first_dir = tmp_path / "first-package"
    first_dir.mkdir()
    first_dir.chmod(0o700)
    first = extractor.extract(
        make_archive({"facts.md": "Teams understand files."}), first_dir
    )
    branch = "minime/bootstrap/deterministic"
    git("checkout", "-b", branch, cwd=repo)
    openspec = OpenSpecAdapter()
    openspec.install_official_integrations(repo, ["codex"])
    incoming = repo / "context/incoming" / first.sha256
    incoming.mkdir(parents=True)
    for relative in first.files:
        target = incoming / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((first_dir / relative).read_bytes())
    populate(repo, first.sha256, first.files, incremental=False)
    GreenfieldBootstrapCoordinator._validate_candidate(repo, incoming, first.files, first_dir)
    git("add", ".", cwd=repo)
    git("commit", "-m", "docs: deterministic bootstrap context", cwd=repo)
    first_head = git("rev-parse", "HEAD", cwd=repo)
    adapter = RecordingPrAdapter()
    adapter.push_branch(repo, "origin", branch, first_head)
    adapter.create_pr(branch, "main", first_head)
    assert git("rev-parse", "refs/heads/main", cwd=repo) == base_sha

    # Human-approved first merge is simulated locally before incremental work.
    git("checkout", "main", cwd=repo)
    git("merge", "--ff-only", branch, cwd=repo)
    approved_sha = git("rev-parse", "HEAD", cwd=repo)

    second_dir = tmp_path / "second-package"
    second_dir.mkdir()
    second_dir.chmod(0o700)
    second = extractor.extract(
        make_archive({"planning.md": "Historical roadmap only."}), second_dir
    )
    second_branch = "minime/context/deterministic-incremental"
    git("checkout", "-b", second_branch, cwd=repo)
    openspec.install_official_integrations(repo, ["codex"])
    second_incoming = repo / "context/incoming" / second.sha256
    second_incoming.mkdir(parents=True)
    for relative in second.files:
        target = second_incoming / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((second_dir / relative).read_bytes())
    populate(repo, second.sha256, second.files, incremental=True)
    GreenfieldBootstrapCoordinator._validate_candidate(
        repo, second_incoming, second.files, second_dir
    )
    assert git("rev-parse", "refs/heads/main", cwd=repo) == approved_sha
    git("add", ".", cwd=repo)
    git("commit", "-m", "docs: deterministic incremental context", cwd=repo)
    second_head = git("rev-parse", "HEAD", cwd=repo)
    adapter.push_branch(repo, "origin", second_branch, second_head)
    adapter.create_pr(second_branch, "main", second_head)

    assert [pr["branch"] for pr in adapter.prs] == [branch, second_branch]
    assert git("rev-parse", "refs/heads/main", cwd=repo) == approved_sha
    assert "backlog" not in "\n".join(path.name for path in repo.rglob("*"))
    assert (repo / "context/incoming" / first.sha256 / "facts.md").read_text() == (
        "Teams understand files."
    )
