# Security and Secrets

## Host layout
Recommended runtime secret/config location:
`/etc/minime/minime.yaml`, `/etc/minime/minime.env`, `/etc/minime/secrets/` with owner-only/service-appropriate permissions.

## Rules
- Real secrets never enter Git/OpenSpec/GitHub Project fields/log prose.
- Repository contains only example env/config and secret variable names.
- Daemon runs as a dedicated unprivileged user.
- PostgreSQL runtime role is scoped to mini me's database; provisioning/admin credentials are temporary and not retained by daemon.
- GitHub App receives minimum repository permissions and is installed only on repos mini me manages.
- DeepSeek and OpenRouter credentials are independent; never proxy DeepSeek credentials through OpenRouter.
- Project provider allowlists are enforced before transmitting repository content externally.
- Redact secret-like values from structured logs, events and persisted provider outputs.
- Budget/security/provider-policy changes require authorized human action.
