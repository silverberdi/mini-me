## MODIFIED Requirements

### Requirement: Context-efficient candidate review payload construction
The system SHALL construct the complementary review payload sent to the reviewer agent using the exact git diff between `base_sha` and `candidate_sha` combined with the full file content of ONLY candidate-modified, newly added, and deleted files, as well as the active OpenSpec change specifications (`openspec/changes/<change>/`). The system SHALL NOT serialize unchanged static repository files solely because they are tracked in git. The system SHALL preserve full-tree candidate identity, manifest generation, and manifest hash (`manifest_hash`) verification against the candidate worktree in durable storage.

#### Scenario: Review payload for standard functional change stays within context bounds
- **GIVEN** a frozen candidate with a small functional change (e.g. comparable to `parse-normalized-tags`) in a repository containing extensive static documentation or agent tooling
- **WHEN** the code review service prepares the review payload
- **THEN** the payload includes the exact git diff, the contents of modified and newly added implementation and test files, and the active change specification
- **AND** static, unchanged files outside the change are excluded from the payload
- **AND** the resulting prompt token count remains under 5,000 tokens, achieving greater than 90% input token reduction compared to full-tree serialization.

#### Scenario: Candidate manifest hash verification remains full-tree bound
- **GIVEN** a frozen candidate and worktree
- **WHEN** `CandidateManifestService` computes the manifest hash
- **THEN** the manifest hash is computed over all tracked files in the candidate tree
- **AND** payload reduction for the reviewer API does not weaken or alter the stored candidate manifest hash or candidate SHA validation.

#### Scenario: Review diff sanitization and size bounding fail-closed
- **GIVEN** a code review payload preparation for an exact candidate
- **WHEN** git diff contains sensitive credentials, secrets, or API keys
- **THEN** the system sanitizes the diff using secret redaction (`redact_secrets`) before transmission to the reviewer model
- **AND** if the candidate diff exceeds the configured maximum allowable bound (`MAX_REVIEW_DIFF_BYTES`), the review service SHALL fail closed with an explicit preflight error rather than silently truncating modification evidence.

### Requirement: Unconditional inclusion of security, policy, and workflow modifications
The system SHALL NOT unconditionally exclude `.agent/`, `.agents/`, `.openspec/`, or configuration paths from the review payload. Whenever a candidate modifies, adds, or deletes files within agent skills, workflows, repository rules, permissions, or security boundaries, the system SHALL explicitly include those modified files and their diffs in the review payload.

#### Scenario: Security policy modification is fully presented to reviewer
- **GIVEN** a candidate that modifies an agent instruction, hook contract, or repository security rule within `.agent/` or `.agents/`
- **WHEN** the code review payload is generated
- **THEN** the modified policy or instruction file is fully included in the files array and diff
- **AND** the reviewer has complete visibility to evaluate security and permissions regressions.

#### Scenario: Deleted file evidence preserves structural and security context
- **GIVEN** a candidate that deletes a previously tracked file
- **WHEN** the review payload is assembled
- **THEN** the payload includes the deleted path marker along with sufficient structural context (such as the base file content or deletion diff) to enable the reviewer to evaluate the safety of the deletion.
