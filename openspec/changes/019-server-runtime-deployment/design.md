# Design Decisions: 019 Server Runtime Deployment

## 1. System Architecture & Boundaries

```
                 +----------------------------------------------------+
                 |               Ubuntu 26.04 Server                  |
                 |                 192.168.0.194                      |
                 |                                                    |
 LAN Clients --->| :8787  [minime-api.service]                        |
 (Browser/PWA)   |          FastAPI + Static PWA (Vanilla JS/CSS)     |
                 |                                                    |
                 |        [minime-scheduler.service]                  |
                 |          Autonomous SDLC Scheduler                 |
                 |            |          |          |                 |
                 |            v          v          v                 |
                 |         Codex CLI    agy     DeepSeek Direct       |
                 |            |                                       |
                 |            v                                       |
                 |   /var/lib/minime/worktrees/                       |
                 |   Docker Previews (bridge network)                 |
                 |            |                                       |
                 |            v                                       |
                 |   PostgreSQL (local-ai-stack-postgres-1 :5432)     |
                 +----------------------------------------------------+
```

## 2. Canonical Directory Structure
- `/opt/minime/app`: Canonical repository clone tracking `main`.
- `/opt/minime/runtime/venv`: Python 3.14 production virtualenv containing all dependencies and `minime` CLI.
- `/etc/minime/minime.yaml`: Canonical declarative configuration.
- `/etc/minime/minime.env`: Restricted environment variables (`0600`).
- `/etc/minime/secrets/`: Cryptographic secrets (`github-app.pem`) (`0700` dir, `0600` file).
- `/var/lib/minime/worktrees`: Ephemeral candidate worktrees.
- `/var/lib/minime/state`: Runtime locks and state.
- `/var/lib/minime/previews`: Candidate container preview compose files.
- `/var/log/minime`: Operational log targets (supplemented by systemd journal).

## 3. Service Identity & Permissions
- Dedicated system account: `minime` (no interactive login shell `/usr/sbin/nologin`).
- Group membership: `minime`, `docker` (enabling Docker preview lifecycle management without root).
- File ownership: Restricted to `minime:minime`.

## 4. Headless Execution & Resilience
- Services managed by `systemd` with `Restart=always` and `RestartSec=5..10`.
- Enabled via `systemctl enable minime-api minime-scheduler` to ensure boot-time start without requiring graphical desktop login or active SSH sessions.
- Clean recovery on reboot verified by controlled system reboot test.

## 5. Security Posture
- LAN-only binding on port 8787 (`http://192.168.0.194:8787`).
- Zero Mac paths or environment references in production config.
- Zero secrets committed to git.
- Explicit non-exposure to Internet until 019.3 Google Auth and 019.4 Cloudflare Tunnel are implemented in subsequent slices.
