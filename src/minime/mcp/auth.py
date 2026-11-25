from __future__ import annotations

import hashlib
import secrets
import httpx
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from minime.mcp.security import CredentialCipher


@dataclass(frozen=True)
class OAuthAuthorization:
    state: str
    expires_at: datetime


@dataclass(frozen=True)
class OAuthState:
    session_id: str
    project_id: str
    connection_id: str
    expires_at: datetime


class OAuthStateStore:
    def __init__(self):
        self._states: dict[str, OAuthState] = {}

    def issue(self, session_id: str, *, project_id: str = "", connection_id: str = "") -> OAuthAuthorization:
        state = secrets.token_urlsafe(32)
        expires = datetime.now(UTC) + timedelta(minutes=10)
        self._states[hashlib.sha256(state.encode()).hexdigest()] = OAuthState(
            session_id, project_id, connection_id, expires
        )
        return OAuthAuthorization(state, expires)

    def consume(self, state: str, session_id: str) -> bool:
        key = hashlib.sha256(state.encode()).hexdigest()
        expected = self._states.get(key)
        if not expected or expected.session_id != session_id or expected.expires_at <= datetime.now(UTC):
            return False
        self._states.pop(key, None)
        return True

    def consume_context(self, state: str, session_id: str) -> OAuthState | None:
        key = hashlib.sha256(state.encode()).hexdigest()
        expected = self._states.get(key)
        if not expected or expected.session_id != session_id or expected.expires_at <= datetime.now(UTC):
            return None
        self._states.pop(key, None)
        return expected


class OAuthClient:
    """Small OAuth token client; token bodies never cross the API boundary."""

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=10.0)

    def exchange_code(self, token_endpoint: str, code: str, redirect_uri: str, client_id: str, client_secret: str) -> dict[str, Any]:
        return self._token_request(token_endpoint, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "client_id": client_id, "client_secret": client_secret})

    def refresh(self, token_endpoint: str, refresh_token: str, client_id: str, client_secret: str) -> dict[str, Any]:
        return self._token_request(token_endpoint, {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id, "client_secret": client_secret})

    def _token_request(self, endpoint: str, data: dict[str, str]) -> dict[str, Any]:
        try:
            response = self.client.post(endpoint, data=data)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError("OAuth token exchange failed") from exc
        if not isinstance(payload, dict) or not payload.get("access_token"):
            raise RuntimeError("OAuth provider returned no access token")
        return payload


def validate_token_credentials(auth_type: str, credentials: dict[str, Any]) -> None:
    if auth_type == "api_key" and not credentials.get("key"):
        raise ValueError("API key is required")
    if auth_type == "bearer" and not credentials.get("token"):
        raise ValueError("Bearer token is required")
