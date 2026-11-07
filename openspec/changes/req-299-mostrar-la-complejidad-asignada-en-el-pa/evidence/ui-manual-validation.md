# Task 2.3 — Manual browser validation

- Date: 2026-11-06
- Base SHA: `c9c22b44eedf731fc1adbfb8518bed682492ed8f`
- Candidate SHA: 696559529be31728359df14d74a39772c4a341bc (immutable commit). The Angular component and frontend tests in this commit are byte-identical to those exercised in the recorded headless browser validation; subsequent edits in the worktree were limited to OpenSpec evidence wording.
- Browser: Google Chrome headless 149, clean disposable profile
- Viewport: `1440x1000` CSS pixels, desktop
- App: exact frontend candidate, Angular production build served locally; each scenario used an explicit selected-Run payload through the same-origin preview path

| Scenario | Visible result | Negative check | Result |
| --- | --- | --- | --- |
| 2.3-a `high` with evidence | Complexity panel showed `high`, evidence, and the message that proposal and code review are required; it explicitly did not claim reviews were completed. | — | PASS |
| 2.3-b `moderate` | Complexity panel showed `moderate`. | No high-complexity review message. | PASS |
| 2.3-b `low` | Complexity panel showed `low`. | No high-complexity review message. | PASS |
| 2.3-c missing complexity | Complexity panel showed `Pendiente`. | No `high`, `moderate`, or `low` level appeared in the panel. | PASS |
| 2.3-d evidence present | Complexity panel showed `moderate` and the supplied evidence text. | — | PASS |
| 2.3-d evidence absent | Complexity panel showed `low`. | No `Evidencia:` text appeared. | PASS |

The browser assertions inspected the rendered `aria-label="Complejidad asignada"` panel after navigation to `/trabajo-actual` and confirmed the visible text for every scenario. No screenshot from another candidate was reused.
