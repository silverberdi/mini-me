from minime.db.repository import PostgresPersistenceUnitOfWork
from minime.db.session import db_manager
from minime.domain.models import ProjectAgentProfile, ProjectConfigurationPatch
from minime.services.project_service import ProjectService


def reconcile() -> bool:
    with db_manager.session() as session:
        uow = PostgresPersistenceUnitOfWork(session)
        service = ProjectService(uow)
        project = service.get_project("mini-me")
        if not project:
            print("Project mini-me not found in database.")
            return False

        current_profiles = dict(project.agent_profiles or {})

        # 1. Reconcile reviewer to Antigravity + gemini-3.8-flash-medium
        raw_review = current_profiles.get("independent_review", {})
        if isinstance(raw_review, ProjectAgentProfile):
            raw_review = raw_review.model_dump()
        review_profile = ProjectAgentProfile(
            agent_id="antigravity",
            model_id="gemini-3.8-flash-medium",
            effort="medium",
            workflows=raw_review.get("workflows") or ["/opsx-verify"],
            skills=raw_review.get("skills") or [],
        )

        # 2. Reconcile thinking and execution to Codex + gpt-5.6-luna
        raw_thinking = current_profiles.get("thinking", {})
        if isinstance(raw_thinking, ProjectAgentProfile):
            raw_thinking = raw_thinking.model_dump()
        thinking_profile = ProjectAgentProfile(
            agent_id="codex",
            model_id="gpt-5.6-luna",
            effort=raw_thinking.get("effort") or "medium",
            workflows=raw_thinking.get("workflows") or ["$openspec-propose", "$openspec-explore"],
            skills=raw_thinking.get("skills") or ["openspec-propose", "openspec-explore"],
        )

        raw_exec = current_profiles.get("execution", {})
        if isinstance(raw_exec, ProjectAgentProfile):
            raw_exec = raw_exec.model_dump()
        exec_profile = ProjectAgentProfile(
            agent_id="codex",
            model_id="gpt-5.6-luna",
            effort=raw_exec.get("effort") or "medium",
            workflows=raw_exec.get("workflows") or ["$openspec-apply-change", "$openspec-update-change"],
            skills=raw_exec.get("skills") or ["openspec-apply-change", "openspec-update-change"],
        )

        # 3. Preserve fallback profile 100% untouched as required by F2 governance
        raw_fb = current_profiles.get("fallback", {})
        if isinstance(raw_fb, ProjectAgentProfile):
            fallback_profile = raw_fb
        elif isinstance(raw_fb, dict) and raw_fb:
            fallback_profile = ProjectAgentProfile(**raw_fb)
        else:
            fallback_profile = ProjectAgentProfile(
                agent_id="codex",
                model_id="gpt-5.6-luna",
                effort="medium",
                workflows=["$openspec-apply-change"],
                skills=["openspec-apply-change"],
            )

        updated_profiles = {
            "thinking": thinking_profile,
            "execution": exec_profile,
            "independent_review": review_profile,
            "fallback": fallback_profile,
        }

        patch = ProjectConfigurationPatch(agent_profiles=updated_profiles)
        updated = service.update_configuration("mini-me", patch)
        session.commit()
        print("SUCCESS: Project mini-me profiles reconciled via ProjectService.update_configuration().")
        print(updated.agent_profiles)
        return True


if __name__ == "__main__":
    reconcile()
