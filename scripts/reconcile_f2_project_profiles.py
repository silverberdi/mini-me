from minime.db.models import ProjectModel
from minime.db.session import db_manager


def reconcile():
    with db_manager.session() as session:
        proj = session.query(ProjectModel).filter(ProjectModel.id == 'mini-me').first()
        if not proj:
            print("Project mini-me not found in database.")
            return False
        profiles = dict(proj.agent_profiles or {})

        # 1. Reconcile reviewer to Antigravity + gemini-3.8-flash-medium
        profiles["independent_review"] = {
            "agent_id": "antigravity",
            "model_id": "gemini-3.8-flash-medium",
            "effort": "medium",
            "workflows": ["/opsx-verify"],
            "skills": [],
        }

        # 2. Reconcile thinking and execution to Codex + gpt-5.6-luna
        if "thinking" in profiles:
            profiles["thinking"]["agent_id"] = "codex"
            profiles["thinking"]["model_id"] = "gpt-5.6-luna"
            profiles["thinking"]["effort"] = "medium"
        if "execution" in profiles:
            profiles["execution"]["agent_id"] = "codex"
            profiles["execution"]["model_id"] = "gpt-5.6-luna"
            profiles["execution"]["effort"] = "medium"
        if "fallback" in profiles:
            profiles["fallback"]["agent_id"] = "codex"
            profiles["fallback"]["model_id"] = "gpt-5.6-luna"
            profiles["fallback"]["effort"] = "medium"

        proj.agent_profiles = profiles
        session.commit()
        print("SUCCESS: Project mini-me profiles reconciled successfully.")
        import json
        print(json.dumps(proj.agent_profiles, indent=2))
        return True

if __name__ == "__main__":
    reconcile()
