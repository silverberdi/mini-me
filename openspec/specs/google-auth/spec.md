# Specification: Google Authentication and Operator Authorization

## Purpose

Defines Google OIDC authentication, operator authorization, session handling, frontend login access, and authentication audit logging.

## Requirements

### Requirement: Unauthenticated Request Rejection

Any request to a non-whitelisted endpoint without a valid session cookie or bearer token MUST return HTTP status `401 Unauthorized`. The response body MUST contain a standardized error detail and not leak internal state or configuration.

#### Scenario: Unauthenticated request is rejected
- **GIVEN** a client without a valid session cookie or bearer token
- **WHEN** it requests a non-whitelisted endpoint
- **THEN** the endpoint returns `401 Unauthorized` with a standardized error detail and no internal state or configuration leakage.

### Requirement: Google OIDC Token Validation

OAuth callbacks MUST validate the `state` parameter against the issuing session/cache to prevent CSRF. ID tokens MUST be verified against Google's public JWK keys. Tokens with invalid signatures, expired timestamps (`exp`), mismatched audiences (`aud != client_id`), unapproved issuers (`iss != accounts.google.com` and `iss != https://accounts.google.com`), or unverified email addresses (`email_verified != true`) MUST be rejected with HTTP status `401 Unauthorized`.

#### Scenario: OAuth state and identity token are validated
- **GIVEN** an OAuth callback with a missing or mismatched `state`, or an ID token with an invalid signature, expiration, audience, issuer, or unverified email
- **WHEN** the callback is processed
- **THEN** the state check prevents CSRF and invalid tokens are rejected with `401 Unauthorized`.

### Requirement: Operator Authorization Policy

A valid Google identity that is NOT listed in the `authorized_operators` table or configuration MUST be rejected with HTTP status `403 Forbidden` (`IDENTITY_NOT_ALLOWLISTED`). An authorized operator whose `is_active` status is `False` MUST be rejected with HTTP status `403 Forbidden` (`IDENTITY_DISABLED`). An authorized operator with `is_active == True` MUST be granted access and receive an authenticated session.

#### Scenario: Identity is not an authorized operator
- **GIVEN** a valid Google identity absent from the authorized operator list
- **WHEN** authorization is evaluated
- **THEN** access is rejected with `403 Forbidden` (`IDENTITY_NOT_ALLOWLISTED`).

#### Scenario: Operator is disabled
- **GIVEN** an authorized operator whose `is_active` status is `False`
- **WHEN** authorization is evaluated
- **THEN** access is rejected with `403 Forbidden` (`IDENTITY_DISABLED`).

#### Scenario: Active operator is authenticated
- **GIVEN** an authorized operator whose `is_active` status is `True`
- **WHEN** authorization is evaluated
- **THEN** access is granted and an authenticated session is issued.

### Requirement: Server-Side Session Management

Sessions MUST be identified by high-entropy opaque random strings. Only the cryptographic hash (SHA-256) of the session token MUST be stored in the database. Sessions MUST expire after their configured duration (default: 7 days). Expired sessions MUST be rejected with HTTP status `401 Unauthorized`. A call to `POST /api/v1/auth/logout` MUST immediately invalidate the session in the database and clear the `minime_session` cookie.

#### Scenario: Session token is stored and expires safely
- **GIVEN** an authenticated session
- **WHEN** its token is persisted and its configured duration elapses
- **THEN** only the SHA-256 hash is stored and the expired session is rejected with `401 Unauthorized` (default duration: 7 days).

#### Scenario: Logout invalidates the session
- **GIVEN** an active authenticated session
- **WHEN** `POST /api/v1/auth/logout` is called
- **THEN** the database session is immediately invalidated and the `minime_session` cookie is cleared.

### Requirement: Frontend Login Experience & Zero Telemetry Leakage

When an unauthenticated client accesses `/` or `/dashboard`, the PWA MUST render a dedicated login screen containing a "Sign in with Google" button. The PWA MUST NOT fetch or display operational metrics, queue items, active runs, provider status, or change details until authentication succeeds. When authenticated, the PWA top bar MUST display the operator's email, a "Google" provider badge, and a functional "Sign out" button.

#### Scenario: Unauthenticated user sees login without operational data
- **GIVEN** an unauthenticated client
- **WHEN** it accesses `/` or `/dashboard`
- **THEN** the PWA shows a dedicated screen with a "Sign in with Google" button and does not fetch or display operational data.

#### Scenario: Authenticated user sees identity and sign-out
- **GIVEN** an authenticated operator
- **WHEN** the PWA top bar is rendered
- **THEN** it displays the operator's email, a "Google" provider badge, and a functional "Sign out" button.

### Requirement: Audit Logging

Every authentication attempt, authorization decision, logout, and session expiration/revocation MUST be recorded in `auth_audit_events`. Secrets, client secrets, access tokens, and raw session tokens MUST NEVER be recorded in audit logs or application logs.

#### Scenario: Authentication events are audited without secrets
- **GIVEN** an authentication attempt, authorization decision, logout, or session expiration/revocation
- **WHEN** the event is recorded
- **THEN** it is written to `auth_audit_events` and no secret, client secret, access token, or raw session token is written to audit or application logs.
