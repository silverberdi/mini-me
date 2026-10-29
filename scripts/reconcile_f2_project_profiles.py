from minime.db.session import db_manager
from minime.domain.models import ProjectAgentProfile, ProjectConfigurationPatch
from minime.services.project_service import ProjectService


def reconcile():
    with db_manager.session() as session:
        from minime.adapters.sql_persistence import SqlPersistenceUnitOfWork
        uow = SqlPersistenceUnitOfWork(session)
        service = ProjectService(uow)
        project = service.get_project("mini-me")
        if not project:
            print("Project mini-me not found in database.")
            return False

        profiles = dict(project.agent_profiles or {})

        # 1. Reconcile reviewer to Antigravity + gemini-3.8-flash-medium
        profiles["independent_review"] = ProjectAgentProfile(
            agent_id="antigravity",
            model_id="gemini-3.8-flash-medium",
            effort="medium",
            workflows=["/opsx-verify"],
            skills=[],
        )

        # 2. Reconcile thinking and execution to Codex + gpt-5.6-luna
        if "thinking" in profiles:
            current_thinking = profiles["thinking"]
            profiles["thinking"] = ProjectAgentProfile(
                agent_id="codex",
                model_id="gpt-5.6-luna",
                effort=getattr(current_thinking, "effort", "medium") or "medium",
                workflows=getattr(current_thinking, "workflows", []) or ["$openspec-propose", "$openspec-explore"],
                skills=getattr(current_thinking, "skills", []) or ["openspec-propose", "openspec-explore"],
            )

        if "execution" in profiles:
            current_exec = profiles["execution"]
            profiles["execution"] = ProjectAgentProfile(
                agent_id="codex",
                model_id="gpt-5.6-luna",
                effort=getattr(current_exec, "effort", "medium") or "medium",
                workflows=getattr(current_exec, "workflows", []) or ["$openspec-apply-change", "$openspec-update-change"],
                skills=getattr(current_exec, "skills", []) or ["openspec-apply-change", "openspec-update-change"],
            )

        # 3. Preserve fallback profile untouched as required by F2 governance
        if "fallback" in profiles:
            fb = profiles["fallback"]
            if not isinstance(fb, ProjectAgentProfile):
                profiles["fallback"] = ProjectAgentProfile(
                    agent_id=getattr(fb, "agent_id", "codex") or "codex",
                    model_id=getattr(fb, "model_id", "gpt-5.6-sol") or "gpt-5.6-sol",
                    effort=getattr(fb, "effort", "medium") or "medium",
                    workflows=getattr(fb, "workflows", []) or ["$openspec-apply-change"],
                    skills=getattr(fb, "skills", []) or ["openspec-apply-change"],
                )

        patch = ProjectConfigurationPatch(agent_profiles=profiles)
        updated = service.update_configuration("mini-me", patch)
        session.commit()
        print("SUCCESS: Project mini-me profiles reconciled via ProjectService.update_configuration().")
        print(updated.agent_profiles)
        return True

if __name__ == "__main__":
    reconcile()
