#!/usr/bin/env bash
set -euo pipefail
printf 'mini me context doctor\n'
for f in README.md AGENTS.md openspec/config.yaml docs/CANONICAL_DECISIONS.md openspec/changes/001-foundation/proposal.md; do
  [[ -f "$f" ]] || { echo "MISSING: $f"; exit 1; }
done
command -v openspec >/dev/null && openspec --version || echo 'WARN: openspec not found'
command -v codex >/dev/null && codex --version || echo 'WARN: codex not found/auth not checked'
command -v agy >/dev/null && agy --version || echo 'WARN: agy (Antigravity CLI) not found/auth not checked'
command -v git >/dev/null && git --version || { echo 'ERROR: git missing'; exit 1; }
if command -v openspec >/dev/null; then
  openspec validate --all || exit 1
fi
echo 'PASS: context structure looks valid.'
