# Change Proposal: 019 — Server Runtime & Production Deployment

## Intent
Migrate the canonical **mini me** autonomous execution loop, API, PWA serving, and worktree runtime from the local macOS development machine to the dedicated Linux server (`192.168.0.194`).

## Deliverables in Scope
1. **019.1 — Server Bootstrap**:
   - Environment inventory and canonical path provisioning (`/opt/minime`, `/etc/minime`, `/var/lib/minime`, `/var/log/minime`).
   - Dedicated unprivileged system user `minime` in `docker` group.
   - Production Python virtualenv with `minime` CLI and dependencies.
   - Canonical PostgreSQL connectivity to `127.0.0.1:5432/minime` without modifying database schema or credentials.
   - GitHub App credentials deployment and validation.
   - Headless Codex CLI and Antigravity CLI installation/configuration.
   - DeepSeek direct API key configuration and read-only audit verification.
   - Headless Google Chrome verification.
2. **019.2 — Server Runtime**:
   - Systemd units: `minime-api.service` and `minime-scheduler.service`.
   - LAN-only PWA serving on port `8787` (`http://192.168.0.194:8787/`).
   - Managed worktrees executing on `/var/lib/minime/worktrees`.
   - Container preview capability operating against server Docker daemon.
   - Service restart and controlled reboot recovery validation without graphical login.
   - Mac runtime dependency eradication audit.
   - Deployment, update, and health check automation scripts (`scripts/server_bootstrap.sh`, `scripts/deploy_update.sh`, `scripts/health_check.sh`).

## Non-Goals (Deferred to 019.3 / 019.4 / 019.5)
- Google OAuth authentication (019.3).
- Cloudflare Tunnel and public Internet exposure (019.4).
- Final Mac-independent proving run (019.5).
