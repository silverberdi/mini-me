from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from minime.mcp.security import CredentialCipher


@dataclass(frozen=True)
class OAuthAuthorization:
    state: str
    expires_at: datetime


class OAuthStateStore:
    def __init__(self):
        self._states: dict[str, tuple[str, datetime]] = {}

    def issue(self, session_id: str) -> OAuthAuthorization:
        state = secrets.token_urlsafe(32)
        expires = datetime.now(UTC) + timedelta(minutes=10)
        self._states[hashlib.sha256(state.encode()).hexdigest()] = (session_id, expires)
        return OAuthAuthorization(state, expires)

    def consume(self, state: str, session_id: str) -> bool:
        key = hashlib.sha256(state.encode()).hexdigest()
        expected = self._states.get(key)
        if not expected or expected[0] != session_id or expected[1] <= datetime.now(UTC):
            return False
        self._states.pop(key, None)
        return True


def validate_token_credentials(auth_type: str, credentials: dict[str, Any]) -> None:
    if auth_type == "api_key" and not credentials.get("key"):
        raise ValueError("API key is required")
    if auth_type == "bearer" and not credentials.get("token"):
        raise ValueError("Bearer token is required")
