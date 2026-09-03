"""Google OIDC Authentication and Operator Authorization Services for mini me."""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from datetime import timedelta
from typing import Any

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

from minime.domain.enums import AuthEventType, OperatorAuthDecision
from minime.domain.interfaces import PersistenceUnitOfWork
from minime.domain.models import (
    AuthAuditEvent,
    AuthorizedOperator,
    AuthSession,
    utc_now,
)

logger = logging.getLogger(__name__)

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ["accounts.google.com", "https://accounts.google.com"]


def hash_token(raw_token: str) -> str:
    """Generate SHA-256 hash of a session token for secure database storage."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_state_token() -> str:
    """Generate cryptographically secure state token for OAuth anti-CSRF binding."""
    return secrets.token_urlsafe(32)


def generate_session_token() -> str:
    """Generate high-entropy opaque session token."""
    return secrets.token_urlsafe(32)


class GoogleOidcService:
    """Handles Google OAuth 2.0 / OIDC interactions, token exchange, and JWT verification."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        jwks_uri: str = GOOGLE_JWKS_URI,
        http_client: httpx.Client | None = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.jwks_uri = jwks_uri
        self._http_client = http_client
        self._jwks_cache: dict[str, Any] | None = None
        self._jwks_cache_time: float = 0.0
        self._jwks_ttl: float = 3600.0  # 1 hour

    def _get_client(self) -> httpx.Client:
        return self._http_client or httpx.Client(timeout=10.0)

    def get_authorization_url(
        self,
        redirect_uri: str,
        state: str,
        login_hint: str | None = None,
    ) -> str:
        """Construct Google OAuth 2.0 authorization code request URL."""
        if not self.client_id:
            raise ValueError("Google client_id is not configured")

        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "select_account",
        }
        if login_hint:
            params["login_hint"] = login_hint

        # Standard urllib-safe encoding
        import urllib.parse

        encoded_query = urllib.parse.urlencode(params)
        return f"{GOOGLE_AUTH_ENDPOINT}?{encoded_query}"

    def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        """Exchange authorization code for ID token and access token."""
        if not self.client_id or not self.client_secret:
            raise ValueError("Google OAuth client_id or client_secret is not configured")

        data = {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        client = self._get_client()
        should_close = self._http_client is None
        try:
            resp = client.post(GOOGLE_TOKEN_ENDPOINT, data=data)
            if resp.status_code != 200:
                logger.warning(
                    f"Google token exchange failed with status {resp.status_code}: {resp.text}"
                )
                raise ValueError(f"Token exchange failed with status {resp.status_code}")
            return resp.json()
        finally:
            if should_close:
                client.close()

    def fetch_jwks(self, force_refresh: bool = False) -> dict[str, Any]:
        """Fetch and cache Google's public JSON Web Key Set."""
        now = time.time()
        if (
            not force_refresh
            and self._jwks_cache is not None
            and (now - self._jwks_cache_time) < self._jwks_ttl
        ):
            return self._jwks_cache

        client = self._get_client()
        should_close = self._http_client is None
        try:
            resp = client.get(self.jwks_uri)
            if resp.status_code != 200:
                raise ValueError(f"Failed to fetch JWKS with status {resp.status_code}")
            self._jwks_cache = resp.json()
            self._jwks_cache_time = now
            return self._jwks_cache
        finally:
            if should_close:
                client.close()

    def set_jwks_cache(self, jwks: dict[str, Any]) -> None:
        """Explicitly set JWKS cache (useful for deterministic tests)."""
        self._jwks_cache = jwks
        self._jwks_cache_time = time.time()

    def verify_id_token(
        self,
        id_token_str: str,
        nonce: str | None = None,
    ) -> dict[str, Any]:
        """Verify Google OIDC ID token signature, issuer, audience, expiry, and email verification."""
        if not self.client_id:
            raise ValueError("Google client_id is not configured")

        # 1. Decode unverified header to locate kid
        try:
            unverified_header = jwt.get_unverified_header(id_token_str)
        except Exception as exc:
            raise ValueError(f"Invalid JWT header: {exc}") from exc

        kid = unverified_header.get("kid")
        alg = unverified_header.get("alg", "RS256")
        if not kid:
            raise ValueError("ID token header missing 'kid'")

        # 2. Find matching key in JWKS
        jwks = self.fetch_jwks()
        keys = jwks.get("keys", [])
        key_dict = next((k for k in keys if k.get("kid") == kid), None)

        if not key_dict:
            # Force refresh in case keys were recently rotated
            jwks = self.fetch_jwks(force_refresh=True)
            key_dict = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)

        if not key_dict:
            raise ValueError(f"Public key with kid '{kid}' not found in Google JWKS")

        public_key = RSAAlgorithm.from_jwk(key_dict)

        # 3. Verify signature and claims
        try:
            claims = jwt.decode(
                id_token_str,
                key=public_key,
                algorithms=[alg],
                audience=self.client_id,
                options={"verify_aud": True, "verify_exp": True},
            )
        except jwt.ExpiredSignatureError as exc:
            raise ValueError("ID token has expired") from exc
        except jwt.InvalidAudienceError as exc:
            raise ValueError("ID token audience mismatch") from exc
        except Exception as exc:
            raise ValueError(f"JWT verification failed: {exc}") from exc

        # 4. Check Issuer
        iss = claims.get("iss")
        if iss not in GOOGLE_ISSUERS:
            raise ValueError(f"Invalid ID token issuer: '{iss}'")

        # 5. Check email_verified
        email_verified = claims.get("email_verified")
        if email_verified is not True and str(email_verified).lower() != "true":
            raise ValueError("Google email is not verified")

        # 6. Check nonce if provided
        if nonce and claims.get("nonce") != nonce:
            raise ValueError("ID token nonce mismatch")

        # 7. Check subject
        if not claims.get("sub"):
            raise ValueError("ID token missing 'sub' claim")

        return claims


class SessionManager:
    """Manages creation, lookup, validation, and revocation of server-side sessions."""

    def __init__(self, uow: PersistenceUnitOfWork):
        self.uow = uow

    def create_session(
        self,
        operator_email: str,
        google_sub: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        lifetime_seconds: int = 604800,  # 7 days
    ) -> tuple[str, AuthSession]:
        """Create and persist a new authenticated operator session."""
        raw_token = generate_session_token()
        token_hash = hash_token(raw_token)
        now = utc_now()
        expires_at = now + timedelta(seconds=lifetime_seconds)

        session = AuthSession(
            session_token_hash=token_hash,
            operator_email=operator_email.lower().strip(),
            google_sub=google_sub,
            created_at=now,
            expires_at=expires_at,
            last_seen_at=now,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.uow.auth_sessions.save(session)
        self.uow.commit()
        return raw_token, session

    def validate_session(
        self,
        raw_token: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuthSession | None:
        """Validate raw token against stored session hash; updates last_seen_at if valid."""
        if not raw_token or len(raw_token.strip()) < 16:
            return None

        token_hash = hash_token(raw_token.strip())
        session = self.uow.auth_sessions.get_by_token_hash(token_hash)
        if not session:
            return None

        if not session.is_valid:
            return None

        # Update last seen
        session.last_seen_at = utc_now()
        if ip_address:
            session.ip_address = ip_address
        if user_agent:
            session.user_agent = user_agent
        self.uow.auth_sessions.save(session)
        self.uow.commit()
        return session

    def revoke_session_by_token(self, raw_token: str) -> bool:
        """Revoke session identified by raw token."""
        if not raw_token:
            return False
        token_hash = hash_token(raw_token.strip())
        session = self.uow.auth_sessions.get_by_token_hash(token_hash)
        if session and session.revoked_at is None:
            self.uow.auth_sessions.revoke(session.session_id)
            self.uow.commit()
            return True
        return False

    def revoke_session_by_id(self, session_id: str) -> bool:
        """Revoke session identified by session_id."""
        session = self.uow.auth_sessions.get_by_id(session_id)
        if session and session.revoked_at is None:
            self.uow.auth_sessions.revoke(session_id)
            self.uow.commit()
            return True
        return False

    def revoke_all_for_operator(self, email: str) -> None:
        """Revoke all active sessions for a given operator email."""
        self.uow.auth_sessions.revoke_all_for_operator(email.lower().strip())
        self.uow.commit()


class AuthorizedOperatorService:
    """Evaluates operator authorization against local mini me allowlist policy."""

    def __init__(self, uow: PersistenceUnitOfWork):
        self.uow = uow

    def evaluate_operator(
        self,
        email: str,
        google_sub: str | None = None,
    ) -> tuple[OperatorAuthDecision, AuthorizedOperator | None]:
        """Evaluate if an authenticated identity is an authorized, active operator."""
        normalized_email = email.lower().strip()
        operator = self.uow.authorized_operators.get_by_email(normalized_email)
        if not operator and google_sub:
            operator = self.uow.authorized_operators.get_by_google_sub(google_sub)

        if not operator:
            return OperatorAuthDecision.IDENTITY_NOT_ALLOWLISTED, None

        if not operator.is_active:
            return OperatorAuthDecision.IDENTITY_DISABLED, operator

        # Update google_sub if not yet linked
        if google_sub and not operator.google_sub:
            operator.google_sub = google_sub
            operator.updated_at = utc_now()
            self.uow.authorized_operators.save(operator)
            self.uow.commit()

        return OperatorAuthDecision.AUTHORIZED, operator

    def seed_operator(
        self,
        email: str,
        display_name: str | None = None,
        google_sub: str | None = None,
        is_active: bool = True,
    ) -> AuthorizedOperator:
        """Seed or update an authorized operator in the database."""
        normalized_email = email.lower().strip()
        existing = self.uow.authorized_operators.get_by_email(normalized_email)
        if existing:
            existing.display_name = display_name or existing.display_name
            existing.google_sub = google_sub or existing.google_sub
            existing.is_active = is_active
            existing.updated_at = utc_now()
            self.uow.authorized_operators.save(existing)
            self.uow.commit()
            return existing

        new_operator = AuthorizedOperator(
            email=normalized_email,
            display_name=display_name,
            google_sub=google_sub,
            is_active=is_active,
        )
        self.uow.authorized_operators.save(new_operator)
        self.uow.commit()
        return new_operator

    def record_audit(
        self,
        event_type: AuthEventType,
        operator_email: str | None = None,
        google_sub: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        reason: str | None = None,
    ) -> AuthAuditEvent:
        """Record an immutable audit event for security monitoring."""
        event = AuthAuditEvent(
            event_type=event_type,
            operator_email=operator_email.lower().strip() if operator_email else None,
            google_sub=google_sub,
            ip_address=ip_address,
            user_agent=user_agent,
            reason=reason,
            timestamp=utc_now(),
        )
        self.uow.auth_audit_events.save(event)
        self.uow.commit()
        return event
