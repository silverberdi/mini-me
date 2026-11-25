import pytest

from minime.mcp.auth import validate_token_credentials


def test_token_auth_requires_material():
    validate_token_credentials("api_key", {"key": "k"})
    validate_token_credentials("bearer", {"token": "t"})
    with pytest.raises(ValueError):
        validate_token_credentials("bearer", {})
