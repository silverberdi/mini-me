## ADDED Requirements

### Requirement: Verify dispatch distinguishes native workflow from CLI validation
The system SHALL instruct the configured implementer to execute the installed native OpenSpec Verify workflow through its provider-specific dispatch command. The Verify prompt and installed Verify skill instructions SHALL identify `openspec validate --type change --strict <change-name>` as the CLI command for structural Change validation and SHALL NOT direct users or agents to run `openspec verify` as a CLI command. Clarifying CLI validation SHALL NOT replace, emulate, or bypass the native Verify workflow.

#### Scenario: Verify prompt names the real CLI validation command
- **GIVEN** a candidate has reached the Verify stage
- **WHEN** mini me builds the implementer's Verify prompt
- **THEN** the prompt retains the resolved provider-specific native Verify workflow dispatch
- **AND** identifies `openspec validate --type change --strict <change-name>` as structural CLI validation
- **AND** states that `openspec verify` is not a CLI command.

#### Scenario: Installed Verify skills preserve native provider dispatch
- **GIVEN** the Codex and Antigravity Verify instructions are installed in their canonical skill directories
- **WHEN** either instruction is read for a Verify operation
- **THEN** it distinguishes native workflow dispatch from structural CLI validation
- **AND** retains that provider's native invocation instructions.
