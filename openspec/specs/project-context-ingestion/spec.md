# project-context-ingestion Specification

## Purpose
Safely accept a user-supplied ZIP and have the selected real thinking agent organize only the material actually provided into navigable canonical project context.

## Requirements

### Requirement: Treat uploaded archives as untrusted data
Before persistence or extraction, mini me SHALL enforce finite compressed/uncompressed size, entry-count and path limits; reject absolute paths, traversal, normalized collisions, symlinks/hardlinks, devices, unsupported nested archives or executable content according to the documented archive policy. Extraction SHALL stay in an authorized temporary workspace, SHALL NOT follow links, and SHALL never execute archive content, package hooks or shell instructions. Secret-bearing content SHALL not be committed, sent to GitHub, or supplied as a credential to an agent.

#### Scenario: ZIP path traversal or symlink is present
- **WHEN** an uploaded ZIP contains `..`, an absolute path, a symlink/hardlink, special file, collision, or resource-limit violation
- **THEN** upload is rejected/quarantined before project creation or Git/agent/GitHub mutation and the protected workspace is unchanged

#### Scenario: Archive contains executable instructions or secret material
- **WHEN** content is executable or recognized as a secret-bearing file
- **THEN** it is never run or published; onboarding is blocked with sanitized provenance and no secret is included in agent context/logs/PR

### Requirement: Real thinking agent organizes content faithfully without inventing product intent
For a valid Greenfield onboarding, mini me SHALL invoke the configured, budget-authorized, file-capable thinking agent in the bound bootstrap workspace. The agent SHALL classify and organize only supplied information as product/context documentation, requirements, decisions, restrictions, architecture, references, diagrams, and assets where evidence supports the category; retain source provenance; build a concise index/navigation map; and link canonical context from `AGENTS.md`, applicable existing agent instruction files, and `openspec/config.yaml`. It SHALL preserve compatible existing instructions and SHALL NOT invent features, stories, requirements, decisions, OpenSpec proposals/specs/tasks, or resolve contradictions speculatively.

#### Scenario: Representative context package is organized
- **WHEN** the selected thinking CLI processes a ZIP containing product facts, constraints, a diagram, references, and a stated contradiction
- **THEN** committed context records source paths/provenance, organizes supported categories, links the canonical context, preserves the approved decision unless an explicit replacement was supplied, and flags the contradiction with both source references without adding unsupported product claims

#### Scenario: Documentary contradiction remains reviewable
- **WHEN** a valid package introduces a contradiction with an approved decision but does not declare an explicit replacement
- **THEN** the new document and contradiction record are included in the candidate PR for human review; the contradiction alone does not block publication or change effective context before merge

#### Scenario: Agent cannot prove source fidelity
- **WHEN** the agent's result omits, materially alters, duplicates without reason, or cannot trace substantive supplied information
- **THEN** the candidate fails validation and no bootstrap PR is published as ready

#### Scenario: Existing instructions conflict
- **WHEN** existing AGENTS/agent-equivalent/OpenSpec instructions conflict with a proposed context link or would be overwritten
- **THEN** the original compatible content is preserved and the conflict is reported for explicit resolution rather than overwritten


### Requirement: Populate a standard optional catalog, not an inferred project structure

Mini me SHALL define one fixed, versioned F2 catalog of standard context folders/files (from general and business/product through architecture, UX, data, integrations, security, operations, planning, AI, legal and organization). The file-capable thinking agent SHALL read all admissible original ZIP files and populate the applicable canonical Markdown files with useful summaries/consolidation from **only** provided information. Source-supported information MAY appear in multiple relevant files to make each understandable without forced de-duplication. The catalog determines the file layout; the agent must not invent categories, product facts or implementation tasks.

The agent SHALL preserve unchanged originals under `context/incoming/<sha>/`, record provenance, generate `context/INDEX.md` and optional source index, and index **only** populated files with valid links. Documents with no applicable information MAY remain absent or empty, and SHALL not appear in the index. A received roadmap MAY be represented as documentary roadmap; a received backlog MAY inform historical planning context, but neither SHALL create an operational backlog, GitHub Issues, OpenSpec tasks or authorization to implement.

No semantic or business-quality review is required in F2. Technical checks for ZIP safety, immutable source fidelity, canonical paths, correct navigation, secrets and repository isolation remain mandatory.

#### Scenario: One source fact belongs in several documents
- **WHEN** one supplied statement relates to product, domain and security
- **THEN** it may be faithfully included in all three canonical documents with provenance and without invented technical implementation

#### Scenario: Sparse ZIP leaves catalog documents empty
- **WHEN** no supplied source describes a catalog topic
- **THEN** the corresponding file is absent or empty and is omitted from `context/INDEX.md`; no filler or unsupported claim is generated

#### Scenario: Roadmap and backlog are received as source files
- **WHEN** the ZIP includes a roadmap and an existing backlog
- **THEN** originals remain available, documented planning information may be consolidated into standard contextual planning files, and no executable backlog or ticket is generated

### Requirement: Validate provenance, references, and official OpenSpec configuration before publication
Before commit, mini me SHALL verify every generated context claim has source provenance, all index/config references resolve within the repository, native OpenSpec configuration passes the official CLI validation, and no secret or unrelated destructive change is present. Indexing SHALL avoid bulk duplication by linking to canonical source documents.

#### Scenario: Context passes validation
- **WHEN** the organized content and config references resolve and official OpenSpec validation succeeds
- **THEN** the candidate may proceed to commit on the bootstrap branch

#### Scenario: Link escapes or source is unaccounted for
- **WHEN** an index points outside the repository or substantive output lacks source provenance
- **THEN** validation fails closed and the unvalidated output is not pushed or proposed as effective context
