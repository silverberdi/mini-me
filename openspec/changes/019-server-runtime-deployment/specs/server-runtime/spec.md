# Spec: Server Runtime (019.2)

## ADDED REQUIREMENTS

### Requirement: Autonomous Systemd Services
The server MUST run `minime-api.service` and `minime-scheduler.service` as persistent systemd units under user `minime`.

#### Scenario: Service Health
- Given the systemd units `minime-api.service` and `minime-scheduler.service`
- When `systemctl status minime-api minime-scheduler` is executed
- Then both units are `active (running)`, configured with auto-restart, and log to journald without unhandled exceptions.

### Requirement: LAN PWA Serving
The server API MUST serve the full PWA and REST API over the local area network on port 8787.

#### Scenario: PWA HTTP Availability
- Given the running `minime-api.service`
- When requesting `http://192.168.0.194:8787/` and `http://192.168.0.194:8787/api/health`
- Then `GET /` returns HTTP 200 with HTML/JS PWA assets, and `GET /api/health` returns JSON `{"status": "ok"}`.

### Requirement: Headless Autonomous Execution & Storage
Managed worktrees and container previews MUST execute on server-side paths without local Mac dependencies or GUI requirements.

#### Scenario: Worktree & Preview Smoke Execution
- Given a test invocation within `/var/lib/minime/worktrees`
- When a candidate worktree is created, modified, and cleaned up
- Then the operations succeed on `/var/lib/minime/worktrees` without referencing macOS user directories or keychain.

### Requirement: Reboot Recovery Resilience
All mini me services MUST survive a server restart and automatically recover to an active healthy state without human terminal or desktop login.

#### Scenario: Post-Reboot Verification
- Given a system reboot of `192.168.0.194`
- When the host completes booting
- Then `minime-api` and `minime-scheduler` transition automatically to `active (running)`, PostgreSQL is reachable, and the PWA responds over LAN.
