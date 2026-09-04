# Specification: Google Authentication and Operator Authorization

## Overview
Defines observable behavior and security contracts for Google OIDC authentication and explicit operator authorization on mini me.

## Requirements

### 1. Unauthenticated Request Rejection
- Any request to a non-whitelisted endpoint without a valid session cookie or bearer token MUST return HTTP status `401 Unauthorized`.
- The response body MUST contain a standardized error detail and not leak internal state or configuration.

### 2. Google OIDC Token Validation
- OAuth callbacks MUST validate the `state` parameter against the issuing session/cache to prevent CSRF.
- ID tokens MUST be verified against Google's public JWK keys.
- Tokens with invalid signatures, expired timestamps (`exp`), mismatched audiences (`aud != client_id`), unapproved issuers (`iss != accounts.google.com` and `iss != https://accounts.google.com`), or unverified email addresses (`email_verified != true`) MUST be rejected with HTTP status `401 Unauthorized`.

### 3. Operator Authorization Policy
- A valid Google identity that is NOT listed in the `authorized_operators` table or configuration MUST be rejected with HTTP status `403 Forbidden` (`IDENTITY_NOT_ALLOWLISTED`).
- An authorized operator whose `is_active` status is `False` MUST be rejected with HTTP status `403 Forbidden` (`IDENTITY_DISABLED`).
- An authorized operator with `is_active == True` MUST be granted access and receive an authenticated session.

### 4. Server-Side Session Management
- Sessions MUST be identified by high-entropy opaque random strings.
- Only the cryptographic hash (SHA-256) of the session token MUST be stored in the database.
- Sessions MUST expire after their configured duration (default: 7 days). Expired sessions MUST be rejected with HTTP status `401 Unauthorized`.
- A call to `POST /api/v1/auth/logout` MUST immediately invalidate the session in the database and clear the `minime_session` cookie.

### 5. Frontend Login Experience & Zero Telemetry Leakage
- When an unauthenticated client accesses `/` or `/dashboard`, the PWA MUST render a dedicated login screen containing a "Sign in with Google" button.
- The PWA MUST NOT fetch or display operational metrics, queue items, active runs, provider status, or change details until authentication succeeds.
- When authenticated, the PWA top bar MUST display the operator's email, a "Google" provider badge, and a functional "Sign out" button.

### 6. Audit Logging
- Every authentication attempt, authorization decision, logout, and session expiration/revocation MUST be recorded in `auth_audit_events`.
- Secrets, client secrets, access tokens, and raw session tokens MUST NEVER be recorded in audit logs or application logs.
