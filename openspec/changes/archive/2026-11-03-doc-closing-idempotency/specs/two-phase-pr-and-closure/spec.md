## MODIFIED Requirements

### Requirement: Native OpenSpec Sync and Archive Execution
The system SHALL dynamically resolve the official OpenSpec Sync and Archive workflows for the thinking agent based on the workflows installed in the documentation worktree (`.agent/workflows/opsx-sync.md` and `opsx-archive.md` for Antigravity vs `.agents/skills/openspec-sync-specs/SKILL.md` and `openspec-archive-change/SKILL.md` for Codex) and provider prompt transport. The system SHALL dispatch the thinking agent configured with lowest compatible effort to execute the resolved Sync workflow followed by Archive, SHALL commit and push the resulting documentation changes, and SHALL NOT emulate Sync or Archive via custom Markdown scripts or manual directory moves (`shutil.move`). Before dispatching these workflows on a DOC_CLOSING re-entry, the system SHALL observe the documentation worktree's OpenSpec state. When the Change is already archived and its delta specs are synchronized into the corresponding main specs, the system SHALL skip Sync and Archive and continue to documentation PR preparation and creation; absence from the active changes directory in this verified state SHALL NOT be treated as a fatal error.

#### Scenario: Thinking agent executes native sync and archive
- **GIVEN** the fresh documentation worktree rooted on merged `main`
- **AND** verified presence of native Sync and Archive workflows for the thinking agent
- **WHEN** mini me dispatches the thinking agent with lowest effort to execute native Sync then native Archive
- **THEN** main specs in `openspec/specs/` are updated with the delta specs
- **AND** change folder is archived under `openspec/changes/archive/`
- **AND** the changes are committed and pushed to `doc-close-<numero>-<slug-kebab>` without Python file-moving scripts.

#### Scenario: Emulation avoidance verification
- **GIVEN** execution of documentation closure stage
- **WHEN** mini me coordinates sync and archive
- **THEN** no Python filesystem operations (such as `shutil.move` or regex spec mergers) touch `openspec/`
- **AND** all modifications originate from the native agent runner invocation.

#### Scenario: Re-entry after completed archive proceeds to documentation PR
- **GIVEN** DOC_CLOSING is re-entered on a documentation worktree where the Change is archived and its delta specs are synchronized into the corresponding main specs
- **WHEN** mini me observes that completed state before dispatching Sync or Archive
- **THEN** it skips both native workflows and continues through the existing documentation PR preparation and creation path
- **AND** it does not fail because the Change is absent from the active changes directory.
