# Tasks: 019 Server Runtime Deployment

## 019.1 Server Bootstrap
- [x] 1.1 Create canonical server directory hierarchy (`/opt/minime`, `/etc/minime`, `/var/lib/minime`, `/var/log/minime`) and user `minime`
- [x] 1.2 Deploy repository to `/opt/minime/app` and setup production Python 3.14 virtualenv
- [x] 1.3 Deploy configuration (`/etc/minime/minime.yaml`, `minime.env`, `secrets/github-app.pem`)
- [x] 1.4 Validate PostgreSQL connectivity and current Alembic revision (`016_provider_efficiency_telemetry`)
- [x] 1.5 Install and configure Codex CLI and Antigravity CLI in headless mode
- [x] 1.6 Verify DeepSeek Direct read-only health check and GitHub App JWT/installation token minting
- [x] 1.7 Verify headless Google Chrome browser execution

## 019.2 Server Runtime
- [x] 2.1 Define and deploy systemd service units (`minime-api.service`, `minime-scheduler.service`)
- [x] 2.2 Create repeatable automation scripts (`scripts/server_bootstrap.sh`, `scripts/deploy_update.sh`, `scripts/health_check.sh`)
- [x] 2.3 Start and verify systemd services (`minime-api` and `minime-scheduler`)
- [x] 2.4 Verify LAN PWA and API endpoints (`http://192.168.0.194:8787/`)
- [x] 2.5 Run managed worktree smoke test on `/var/lib/minime/worktrees`
- [x] 2.6 Run preview container smoke test with Docker daemon
- [x] 2.7 Conduct Mac runtime dependency audit
- [x] 2.8 Execute service restart and controlled server reboot recovery test
- [x] 2.9 Verify post-reboot health and generate comprehensive final report
