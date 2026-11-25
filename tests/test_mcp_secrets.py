import pytest
from cryptography.fernet import Fernet

from minime.mcp.security import CredentialCipher, redact


def test_redaction_removes_credentials_from_nested_diagnostics():
    value = redact({"Authorization": "Bearer abc", "nested": {"refresh_token": "secret"}, "message": "api_key=xyz"})
    assert "abc" not in str(value) and "secret" not in str(value) and "xyz" not in str(value)


def test_missing_or_invalid_master_key_fails_closed():
    with pytest.raises(RuntimeError):
        CredentialCipher()
    with pytest.raises(RuntimeError):
        CredentialCipher(Fernet.generate_key()[:-1])
