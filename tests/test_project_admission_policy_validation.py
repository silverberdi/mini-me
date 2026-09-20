"""Admission policy validation at service and HTTP boundaries."""

import pytest
from pydantic import ValidationError

from minime.api.app import ProjectCreateRequest, ProjectUpdateRequest, register_project
from minime.services.project_service import ProjectService

INVALID_POLICIES = [
    {"max_concurrent_jobs": value} for value in (0, -1, True, 1.5, "2")
] + [
    {field: value}
    for field in ("auto_prepare", "auto_admit")
    for value in (0, 1, "false")
]


@pytest.mark.parametrize("policy", INVALID_POLICIES)
def test_service_rejects_invalid_policy_without_mutation(in_memory_uow, policy):
    service = ProjectService(in_memory_uow)
    with pytest.raises(ValueError):
        service.register_project("invalid", "Invalid", "owner/repo", **policy)
    assert service.get_project("invalid") is None

    project = service.register_project("valid", "Original", "owner/repo")
    with pytest.raises(ValueError):
        service.update_project("valid", display_name="Changed", **policy)
    assert project.display_name == "Original"
    assert project.auto_prepare is True
    assert project.auto_admit is True
    assert project.max_concurrent_jobs == 1



def test_create_endpoint_preserves_explicit_policy(in_memory_uow):
    policy = {"auto_prepare": False, "auto_admit": False, "max_concurrent_jobs": 3}
    request = ProjectCreateRequest(
        project_id="policy", display_name="Policy", repository="owner/repo", **policy
    )
    response = register_project(request, in_memory_uow)
    persisted = ProjectService(in_memory_uow).get_project("policy")
    for field, value in policy.items():
        assert getattr(response, field) == value
        assert getattr(persisted, field) == value


@pytest.mark.parametrize("policy", INVALID_POLICIES)
def test_api_request_models_reject_invalid_policy(policy):
    with pytest.raises(ValidationError):
        ProjectCreateRequest(
            project_id="policy", display_name="Policy", repository="owner/repo", **policy
        )
    with pytest.raises(ValidationError):
        ProjectUpdateRequest(**policy)
