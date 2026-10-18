# Candidate-to-reference visual comparison

Candidate under inspection: uncommitted continuation from `bf0e29cf6534ddc9500bcfac08034f95fe383975` (the exact candidate SHA and preview digest remain pending).

The candidate screenshots are real Chrome captures from a disposable, mock-seeded browser fixture. Their names carry `mock-seeded`; they are evidence of layout/rendering only, not operational state or human acceptance. The approved reference images are unchanged inputs in `docs/design/01..08-*.png`.

| Reference | Candidate evidence | Comparison / result |
|---|---|---|
| 01 desktop active Control Center | `browser/desktop-1440x900-mock-seeded.png` | Partial. Spanish shell, authoritative scheduler `UNKNOWN`, active Run, queue and attention are present. The approved composition is substantially denser and exposes planner/activity/providers/metrics in the first view; the candidate has a broad Run detail panel and less activity/provider context. No reference values were copied into the UI. 4.1 remains open. |
| 02 desktop paused Control Center | None | Blocked by missing intentional-pause authority. No PAUSED fixture, screenshot or state was manufactured. |
| 03 desktop running Run drawer | `browser/desktop-running-run-drawer-mock-seeded.png` | Partial. Drawer now overlays the right side within the approved 45–55% width range, dims the background, exposes close, and restores focus to the selected row. It remains materially sparser than the approved reference (many evidence/activity sections are unavailable in this fixture); it is not a visual match. |
| 04 desktop human-merge drawer | None | Blocked by absence of a durable `READY_FOR_HUMAN_MERGE` candidate and bound PR/review evidence in the disposable store. No candidate or review was fabricated. |
| 05 tablet active master-detail | `browser/tablet-1024x768-mock-seeded.png`, `browser/tablet-768x1024-mock-seeded.png` | Partial. Compact selectable rows now apply throughout tablet widths, no horizontal page/table overflow is observed, and detail remains operable. The candidate still differs in information density and panel ordering from the reference. |
| 06 tablet human-review master-detail | None | Blocked by absence of a durable candidate with independent review evidence. |
| 07 mobile active supervision | `browser/mobile-390x844-mock-seeded.png`, `browser/mobile-360x800-mock-seeded.png` | Partial. Bottom navigation, selected Run identity and attention-first detail render without horizontal overflow. The pipeline was changed to vertical rows so stage labels remain intact at phone widths. The current mobile view is still denser and less card-oriented than the reference. |
| 08 mobile paused/human attention | None | Blocked by missing authoritative paused state. No PAUSED state was created for visual coverage. |

The viewport test covers 1440×900, 1024×768, 768×1024, 390×844 and 360×800, captures screenshots, checks overflow and tablet/mobile hierarchy, and opens/closes the desktop drawer. The separate Chrome accessibility test covers both themes, names, contrast tokens, mobile touch target sizes, 200%-equivalent narrow reflow widths (720, 512 and 320 CSS px), and viewport containment of visible controls. These deterministic checks do not replace the required candidate-bound human comparison of all eight states. Therefore task 4.1 remains open; human visual acceptance also remains pending.
