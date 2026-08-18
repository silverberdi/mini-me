# Operations

## Single-installation posture
mini me is optimized for one known Linux host, not generic distribution.

Recommended runtime paths:
- `/opt/minime/` application
- `/etc/minime/` config/secrets
- `/var/lib/minime/repos/` managed clones
- `/var/lib/minime/worktrees/<project-id>/<change-id>/` isolated workspaces
- `/var/log/minime/` logs

## Service
Long-lived daemon under systemd as an unprivileged `minime` user.

## Operational scripts/features eventually required
- bootstrap host/runtime prerequisites
- doctor/health diagnostics
- update/migrations
- PostgreSQL backup
- restore verification

## Backup
Primary backup target is PostgreSQL plus protected configuration/secrets using an encrypted/controlled external copy. Managed repo clones/worktrees are reconstructible from GitHub and are not primary backup assets.

MVP acceptance requires at least one real restore exercise before declaring operational resilience complete.
