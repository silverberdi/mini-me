from pathlib import Path

SKILL_NAMES = (
    "minime-engineering-discipline",
    "minime-real-e2e-proof",
    "minime-safe-retirement",
)


def test_f4_skills_use_portable_context_in_both_agent_installations():
    root = Path(__file__).parents[1]
    for agent_root in (root / ".agents/skills", root / ".agent/skills"):
        for name in SKILL_NAMES:
            content = (agent_root / name / "SKILL.md").read_text(encoding="utf-8")
            assert "AGENTS.md" in content
            assert "context/INDEX.md" in content
            assert "ninguna ruta `docs/`" in content or "rutas `docs/`" in content
            assert "MM-Rxx" not in content.split("##", 1)[0]
            assert "No copies" in content or "no copies" in content or "no exige copiar" in content


def test_f4_skills_do_not_require_mini_me_private_documents():
    root = Path(__file__).parents[1]
    for agent_root in (root / ".agents/skills", root / ".agent/skills"):
        for name in SKILL_NAMES:
            content = (agent_root / name / "SKILL.md").read_text(encoding="utf-8")
            assert "docs/BUSINESS_INTENT.md" not in content
            assert "docs/CHANGE_DELIVERY_CONTRACT.md" not in content
            assert "ficha MM-Rxx" not in content
