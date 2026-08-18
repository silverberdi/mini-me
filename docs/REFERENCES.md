# External References Checked During Pack Generation

Checked 2026-08-16. These are implementation references, not mutable product requirements.

- OpenSpec repository/docs: `https://github.com/Fission-AI/OpenSpec`
- OpenSpec CLI reference: `https://github.com/Fission-AI/OpenSpec/blob/main/docs/cli.md`
- OpenSpec supported tools: `https://github.com/Fission-AI/OpenSpec/blob/main/docs/supported-tools.md`
- OpenSpec customization/config: `https://github.com/Fission-AI/OpenSpec/blob/main/docs/customization.md`
- Codex CLI official docs: `https://developers.openai.com/codex/cli`
- Antigravity CLI official docs: `https://antigravity.google/docs/cli-getting-started`

Important current OpenSpec behavior used by `install-minime-context.sh`:
- Requires Node.js 20.19+ according to current OpenSpec quick start.
- Non-interactive tool selection supports `openspec init --tools antigravity,codex`.
- Antigravity OpenSpec skills live under `.agent/skills`, workflows under `.agent/workflows`.
- Codex OpenSpec integration is skills-only under `.agents/skills`.
- Expanded workflows include `new`, `continue`, `ff`, `verify`, `bulk-archive`, `onboard` in addition to core workflows.
