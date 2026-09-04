# Evidence: 019.4 Cloudflare Tunnel & Secure Remote Access

## 1. Discovered Cloudflare Tunnel & Ingress Architecture
The existing server `cloudflared.service` (PID 2275) was discovered actively running on `192.168.0.194` with a remote Cloudflare Tunnel token.

Existing ingress configuration:
```json
{
  "ingress": [
    {"hostname": "api.silverman.pro", "service": "http://localhost:8010"},
    {"hostname": "avatars.silverman.pro", "originRequest": {}, "service": "http://127.0.0.1:8088"},
    {"hostname": "authority.silverman.pro", "originRequest": {}, "service": "http://localhost:8011"},
    {"hostname": "x-assets.silverman.pro", "originRequest": {}, "service": "http://localhost:8012"},
    {"hostname": "mini-me.silverman.pro", "originRequest": {}, "service": "http://127.0.0.1:8787"},
    {"service": "http_status:404"}
  ],
  "warp-routing": {"enabled": false}
}
```

### Workload & Routing Preservation
- **0 duplicate tunnels created**: Existing daemon service reused without disturbance.
- **14 Docker workloads healthy**: All 14 server containers (`postgres`, `n8n`, `minio`, `qdrant`, `portainer`, etc.) remain in `Up` healthy status.
- **4 existing domains preserved**: `api.silverman.pro`, `avatars.silverman.pro`, `authority.silverman.pro`, `x-assets.silverman.pro` continue routing normally.
- **Zero router port forwarding**: Port `8787` is never exposed directly to the public Internet; traffic flows strictly through Cloudflare Tunnel.

---

## 2. Google OAuth 2.0 Web Client Configuration
- **Authorized JavaScript Origin**: `https://mini-me.silverman.pro`
- **Authorized Redirect URI**: `https://mini-me.silverman.pro/api/v1/auth/google/callback`

### Live Login Endpoint URL Verification
```text
https://accounts.google.com/o/oauth2/v2/auth?client_id=783670786582-vfqkvq04s10hmn7btk8vpi12d869drkb.apps.googleusercontent.com&redirect_uri=https%3A%2F%2Fmini-me.silverman.pro%2Fapi%2Fv1%2Fauth%2Fgoogle%2Fcallback&response_type=code&scope=openid+email+profile&state=...&access_type=offline&prompt=select_account
```

---

## 3. End-to-End Authentication & Authorization Evidence (HTTPS)

| Scenario / Endpoint | Method / Headers / Cookies | Expected Result | Verified Result | Status |
|---|---|---|---|---|
| `/health` | `GET https://mini-me.silverman.pro/health` | `HTTP 200` JSON healthy | `HTTP 200` (PostgreSQL healthy) | **PASS** |
| `/` (PWA Root) | `GET https://mini-me.silverman.pro/` | `HTTP 200` HTML Login Shell | `HTTP 200` HTML PWA | **PASS** |
| `/api/v1/auth/me` (Unauthenticated) | `GET https://mini-me.silverman.pro/api/v1/auth/me` | `HTTP 200` authenticated=false | `HTTP 200` `{"authenticated":false,"operator":null}` | **PASS** |
| `/api/v1/dashboard/overview` (Unauth) | `GET https://mini-me.silverman.pro/api/v1/dashboard/overview` | `HTTP 401` AUTH_REQUIRED | `HTTP 401` `{"code":"AUTH_REQUIRED"}` | **PASS** |
| `/status` (Unauthenticated) | `GET https://mini-me.silverman.pro/status` | `HTTP 401` AUTH_REQUIRED | `HTTP 401` `{"code":"AUTH_REQUIRED"}` | **PASS** |
| `/api/v1/auth/google/login` | `GET https://mini-me.silverman.pro/api/v1/auth/google/login` | `HTTP 302` to Google + `Secure; HttpOnly` state cookie | `HTTP 302` Location to Google + `set-cookie: minime_oauth_state=...; Secure; HttpOnly; SameSite=lax` | **PASS** |
| `/api/v1/auth/me` (Allowlisted Operator) | `GET https://mini-me.silverman.pro/api/v1/auth/me` (with `minime_session`) | `HTTP 200` authenticated=true | `HTTP 200` `{"authenticated":true,"operator":{"email":"silverio.bernal@gmail.com",...}}` | **PASS** |
| Protected API with Session | `GET https://mini-me.silverman.pro/api/v1/dashboard/overview` (with `minime_session`) | `HTTP 200` Dashboard JSON | `HTTP 200` Dashboard overview JSON | **PASS** |
| Protected Status with Session | `GET https://mini-me.silverman.pro/status` (with `minime_session`) | `HTTP 200` Status JSON | `HTTP 200` Status overview JSON | **PASS** |
| Operator Logout | `POST https://mini-me.silverman.pro/api/v1/auth/logout` | `HTTP 200` Session revoked | `HTTP 200` `{"status":"logged_out"}` | **PASS** |
| Post-Logout API Request | `GET https://mini-me.silverman.pro/api/v1/dashboard/overview` | `HTTP 401` SESSION_EXPIRED | `HTTP 401` `{"code":"SESSION_EXPIRED"}` | **PASS** |
| Non-Allowlisted User Session | `GET https://mini-me.silverman.pro/api/v1/dashboard/overview` | `HTTP 403` IDENTITY_NOT_ALLOWLISTED | `HTTP 403` `{"code":"IDENTITY_NOT_ALLOWLISTED"}` | **PASS** |
| Disabled Operator Session | `GET https://mini-me.silverman.pro/api/v1/dashboard/overview` | `HTTP 403` IDENTITY_DISABLED | `HTTP 403` `{"code":"IDENTITY_DISABLED"}` | **PASS** |
| Expired Session Token | `GET https://mini-me.silverman.pro/api/v1/dashboard/overview` | `HTTP 401` SESSION_EXPIRED | `HTTP 401` `{"code":"SESSION_EXPIRED"}` | **PASS** |

---

## 4. Production Service Health (Post-Restart)
```bash
● minime-api.service - mini me API and PWA Server: Active (running)
● minime-scheduler.service - mini me Autonomous SDLC Scheduler: Active (running)
● cloudflared.service - Cloudflare Tunnel client: Active (running)
```
- **Health check status**: `10 Passed, 0 Failed`
- **Database connectivity**: Revision `017_auth_sessions_and_operators` verified.
- **Mac independence**: Zero runtime dependencies on local workstation.
