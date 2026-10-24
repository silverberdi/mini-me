"""Deterministic F2 taxonomy and document-index tests; no model calls."""

import subprocess
from pathlib import Path

import pytest

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
