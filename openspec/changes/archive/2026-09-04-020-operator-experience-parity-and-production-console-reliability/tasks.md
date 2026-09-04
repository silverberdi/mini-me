# Tasks: 020 — Operator Experience Parity & Production Console Reliability

## 1. TUI Production Runtime Configuration (020.2)
- [ ] 1.1 Implement `discover_and_load_env_file()` in `src/minime/config.py` with multi-path discovery (`MINIME_CONFIG_PATH`, `MINIME_ENV_FILE`, `/etc/minime/minime.env`, `.env`).
- [ ] 1.2 Call `discover_and_load_env_file()` at CLI startup in `src/minime/cli/main.py` and in `load_config()`.
- [ ] 1.3 Add unit tests in `tests/unit/test_config.py` validating automatic env discovery, override preservation, and error handling.

## 2. PWA Operator Parity & Action Safety (020.1)
- [ ] 2.1 Fix action discovery attribute mapping in `src/minime/static/js/dashboard.js` (`action.action` vs `action.action_type`).
- [ ] 2.2 Update `executeOperatorAction` in `dashboard.js` to send full `OperatorActionRequest` with optimistic concurrency fields (`expected_stage`, `expected_generation`, `expected_candidate_sha`, `project_id`, `change_name`).
- [ ] 2.3 Implement interactive parameter dialogs for `reassign` (target executor), `resolve_gate` (decision & notes), `retry` (stage selection), and confirmation dialogs for high-impact actions (`cancel`, `recover_locks`, `reconcile_post_merge`).
- [ ] 2.4 Add `Action History` audit tab in `index.html` and `dashboard.js` querying `/api/v1/runs/{run_id}/actions/history`.
- [ ] 2.5 Add `Provider Efficiency & Telemetry` tab in `index.html` and `dashboard.js` querying `/api/v1/efficiency/{project_id}/{change_name}`.
- [ ] 2.6 Enhance `src/minime/static/css/dashboard.css` with responsive breakpoints for Desktop (1366px, 1920px, 2560px), Tablet (768px-1024px), and Mobile (<768px).

## 3. Automated Verification & Tests
- [ ] 3.1 Run unit tests for config, control plane service, API routes, TUI client, and static PWA structure.
- [ ] 3.2 Run linting and formatting (`ruff check`, `ruff format`).

## 4. Production Deployment & Live Proving
- [ ] 4.1 Update code on production server `192.168.0.194`.
- [ ] 4.2 Configure host permissions (`chmod 640 /etc/minime/minime.env`, `usermod -aG minime silverman`) and create `/usr/local/bin/minime` launcher.
- [ ] 4.3 Verify interactive TUI launch (`minime console`, `minime status`) over SSH as user `silverman` with zero manual environment exports.
- [ ] 4.4 Verify public PWA at `https://mini-me.silverman.pro` (desktop, tablet, mobile viewports, action modals, efficiency tab, action history tab).
- [ ] 4.5 Verify shared host health (14 Docker containers and 4 Cloudflare domains).
