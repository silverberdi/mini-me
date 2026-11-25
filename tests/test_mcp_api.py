from minime.api.app import app


def test_mcp_api_exposes_authenticated_management_surface():
    paths = {route.path for route in app.routes}
    assert "/api/v1/projects/{project_id}/mcp-connections" in paths
    assert "/api/v1/projects/{project_id}/mcp-connections/{connection_id}/revoke" in paths
