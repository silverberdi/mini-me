# Tasks: 019.3 Google Authentication & Operator Authorization

## 1. Domain & Persistence Foundation
- [x] 1.1 Add `AuthEventType` and `OperatorAuthDecision` enums to `src/minime/domain/enums.py`
- [x] 1.2 Add `AuthorizedOperator`, `AuthSession`, `AuthAuditEvent`, and DTOs to `src/minime/domain/models.py`
- [x] 1.3 Define repository interfaces in `src/minime/domain/interfaces.py` and update `PersistenceUnitOfWork`
- [x] 1.4 Create Alembic migration `alembic/versions/017_auth_sessions_and_operators.py`
- [x] 1.5 Implement PostgreSQL ORM tables in `src/minime/db/tables.py` and repositories in `src/minime/db/repository.py`
- [x] 1.6 Implement in-memory repositories in `tests/conftest.py`

## 2. Authentication & Authorization Services
- [x] 2.1 Implement `GoogleOidcService` in `src/minime/services/auth_service.py` with OIDC validation (issuer, audience, signature, expiry, verified email, state)
- [x] 2.2 Implement `SessionManager` in `src/minime/services/auth_service.py` with cryptographic token generation, SHA-256 hashing, expiration, and revocation
- [x] 2.3 Implement `AuthorizedOperatorService` in `src/minime/services/auth_service.py` with allowlist checking and audit event emission

## 3. Backend API Security & Routes
- [x] 3.1 Define public route whitelist and `require_authenticated_operator` dependency in `src/minime/api/app.py`
- [x] 3.2 Add auth endpoints: `GET /api/v1/auth/google/login`, `GET /api/v1/auth/google/callback`, `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`
- [x] 3.3 Apply authentication dependency to all operational endpoints (dashboard, queue, runs, control plane, preview, scheduler, providers, budget)

## 4. PWA Frontend UI
- [x] 4.1 Update `src/minime/static/index.html` to add login shell container and top navigation operator badge
- [x] 4.2 Update `src/minime/static/js/dashboard.js` to check `/api/v1/auth/me` on startup, toggle login experience, handle logout, and intercept 401s

## 5. Testing & Security Verification
- [x] 5.1 Implement comprehensive unit & integration tests in `tests/test_google_auth.py`
- [x] 5.2 Validate all 14 required security scenarios (unauthenticated 401, invalid session 401, expired 401, revoked 401, non-allowlisted 403, disabled 403, authorized 200, logout, state anti-CSRF, invalid issuer/audience, audit events, secret leakage prevention)
- [x] 5.3 Verify full pytest suite passes and `ruff check .` has 0 errors
- [x] 5.4 Verify Alembic single head integrity

## 6. Deployment & LAN Acceptance
- [ ] 6.1 Deploy candidate to server `192.168.0.194` (`/opt/minime/app`)
- [ ] 6.2 Apply Alembic migration `017_auth_sessions_and_operators` on PostgreSQL database
- [ ] 6.3 Restart `minime-api.service` and `minime-scheduler.service`
- [ ] 6.4 Verify LAN unauthenticated access presents login shell and direct API calls return 401
- [ ] 6.5 Confirm all 14 existing server containers remain healthy and unaffected
