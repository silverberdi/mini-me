# Change Proposal: 019.3 — Google Authentication & Operator Authorization

## Intent
Protect the **mini me** PWA control center and operational API with Google OpenID Connect (OIDC) / OAuth 2.0 authentication and local explicit operator authorization before public Internet exposure. Unauthenticated or unauthorized callers must be strictly barred from operational control, session state must be securely managed server-side via HttpOnly cookies, and all auth events must be safely audited.

## Deliverables in Scope
1. **Google OIDC Protocol**: Standard authorization code flow with state validation, signature verification against Google JWKs, audience/client ID matching, and email verification.
2. **Operator Authorization Policy**: Distinct authentication vs. authorization enforcement. Allowlist-based authorization checking (`AuthorizedOperatorService`) supporting active/disabled states.
3. **Server-Managed Session Store**: PostgreSQL-backed opaque session tokens (`auth_sessions`), SHA-256 hashed at rest, with explicit configurable expiration and revocation.
4. **Backend Security Boundary**: Centralized FastAPI authentication dependency enforcing protection across all operational endpoints (`401` for unauthenticated, `403` for non-allowlisted), with explicit minimal public whitelist (`/health`, login initiation, OAuth callback, logout, session status, and login static shell).
5. **PWA Login & Identity UI**: Zero operational data exposure prior to authentication, dedicated dense login screen, top navigation operator identity badge, and server-invalidating logout.
6. **Security Audit Logging**: PostgreSQL audit trail (`auth_audit_events`) logging login success, rejection, denial, session expiration, and logout without recording sensitive credentials.

## Non-Goals
- Cloudflare Tunnel and public Internet exposure (deferred to 019.4).
- Complex hierarchical RBAC (a lean allowlist of active authorized operators is standard).
- Client-side token storage in localStorage or IndexedDB.
- Hardcoded personal operator emails in source repository.
