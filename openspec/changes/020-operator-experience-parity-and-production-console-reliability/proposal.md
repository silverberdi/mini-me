# Proposal: 020 — Operator Experience Parity & Production Console Reliability

## Why
With `019-server-runtime-deployment` delivered, mini me runs entirely server-side on `192.168.0.194` with zero Mac dependencies and public HTTPS access via Cloudflare Tunnel. However, two operational challenges exist:
1. **PWA Operator Parity**: While PWA and TUI share the same backend, the PWA does not yet expose full operational parity on desktop and tablet: certain governed operator actions lack parameter modals, dangerous action confirmations, action history audit tabs, and provider efficiency views.
2. **TUI Production Reliability**: When launched interactively over SSH, the TUI does not discover `/etc/minime/minime.env` and fails with `MINIME_DATABASE_URL is not configured`.

## What
Make mini me operable as a true product from the PWA on desktop and tablet, while maintaining the TUI as a robust, single-command SSH fallback. Both surfaces consume the same canonical services, read models, and Control Plane.

Deliver:
- `020.1 — PWA Operator Parity`: Complete action execution, dynamic parameter dialogs, dangerous action confirmations, action audit history tab, provider efficiency tab, and responsive layout across desktop, tablet, and mobile.
- `020.2 — TUI Production Runtime Reliability`: Canonical `.env` discovery in `config.py` and CLI launcher on Linux host, enabling `minime console` over SSH with zero manual variable exports and zero secret leakage.

## Non-Goals
- No new feature scope (e.g. OpenRouter configuration UI, DeepSeek secret UI, new auth providers, Ollama integration, multi-repo onboarding).
- No duplication of business logic in frontend or TUI clients.
- No world-readable secrets or storing secrets in shell profiles/history.
