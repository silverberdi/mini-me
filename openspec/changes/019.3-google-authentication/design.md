# Design: 019.3 Google Authentication & Operator Authorization

## Architecture Overview
mini me separates identity verification (Google OIDC) from operational authorization (`AuthorizedOperatorService`).

```
Browser (Unauthenticated)
   │
   ├─► GET / -> Login Shell (No operational telemetry)
   │
   ├─► GET /api/v1/auth/google/login -> Redirects to accounts.google.com with PKCE/state
   │
   ├─► GET /api/v1/auth/google/callback -> Exchanges code, verifies ID token against JWKs
   │                                     -> Checks AuthorizedOperatorService allowlist
   │                                     -> Issues HttpOnly cookie with opaque session token
   │
Browser (Authenticated Operator)
   │
   ├─► GET /api/v1/dashboard/overview (Cookie: minime_session) -> 200 OK + full dashboard
   ├─► POST /api/v1/control/actions (Cookie: minime_session)   -> 200 OK + executes action
   └─► POST /api/v1/auth/logout                                -> Revokes session, clears cookie
```

## Security & Architectural Decisions

### 1. Separate Authentication and Authorization
- Google provides trusted proof of identity (subject identifier `sub`, verified email).
- mini me's `AuthorizedOperatorService` evaluates if that identity is allowlisted and active in `authorized_operators`.
- Valid Google identity not in allowlist returns `403 Forbidden` (`IDENTITY_NOT_ALLOWLISTED`).

### 2. Session Management
- Sessions use high-entropy random tokens (`secrets.token_urlsafe(32)`).
- Session token is stored in the browser as an `HttpOnly`, `SameSite=Lax` cookie (`minime_session`).
- Database stores only the SHA-256 hash of the session token in `auth_sessions`.
- Sessions support explicit expiration (default 7 days) and instant revocation (`revoked_at`).

### 3. Fail-Closed Route Protection
- Centralized FastAPI dependency `require_authenticated_operator` is injected on all protected endpoints.
- Public routes are strictly enumerated:
  - `GET /health`
  - `GET /api/v1/auth/google/login`
  - `GET /api/v1/auth/google/callback`
  - `POST /api/v1/auth/logout`
  - `GET /api/v1/auth/me`
  - `GET /`, `/dashboard`, `/static/*`, `/sw.js`, `/manifest.webmanifest`, `/favicon.ico`
- All other endpoints require valid authenticated operator context.

### 4. Database Schema
Versioned Alembic migration `017_auth_sessions_and_operators.py` creates:
- `authorized_operators` (id, email, google_sub, display_name, is_active, created_at, updated_at)
- `auth_sessions` (id, session_token_hash, operator_email, google_sub, created_at, expires_at, last_seen_at, revoked_at, ip_address, user_agent)
- `auth_audit_events` (id, event_type, operator_email, google_sub, ip_address, user_agent, reason, timestamp)

### 5. Audit Logging
Every auth lifecycle transition is logged to `auth_audit_events`:
- `LOGIN_SUCCEEDED`
- `LOGIN_REJECTED`
- `AUTHORIZATION_DENIED`
- `LOGOUT`
- `SESSION_EXPIRED`
- `SESSION_REVOKED`
Secrets, client secrets, access tokens, and raw session tokens are never logged.
