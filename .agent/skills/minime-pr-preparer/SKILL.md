---
name: minime-pr-preparer
description: Prepares structured, compliant pull request titles and descriptions for mini me F3 orchestration.
version: "1.0.0"
---

# minime-pr-preparer

This skill produces structured pull request content for both Phase 1 (implementation) and Phase 2 (documentation closure) in the mini me orchestration lifecycle.

## Contract & Rules

1. **Informative Issue References Only (STRICT)**:
   - For both implementation (`pr_type: implementation`) and documentation (`pr_type: documentation`), the issue reference MUST be informative only.
   - Use: `Addresses #<num>`, `Ref #<num>`, `Related to #<num>`.
   - **STRICT PROHIBITION**: NEVER include GitHub auto-closing keywords (`Fixes #...`, `Closes #...`, `Resolves #...`, or any lowercase/past tense variation). The remote issue is closed ONLY by mini me after the Phase 2 documentation PR is verified merged into `main`.

2. **Input Payload Format**:
   - `project_id`: Project identifier.
   - `repository`: Repository name / slug.
   - `pr_type`: Either `implementation` or `documentation`.
   - `issue_number`: Numerical GitHub issue ID.
   - `issue_title`: Title of the original issue.
   - `base_branch`: Target branch (e.g. `main`).
   - `candidate_branch`: Source branch (`request-...` or `doc-close-...`).
   - `candidate_sha`: Verified commit SHA.
   - `change_name`: OpenSpec change identifier.
   - `change_summary`: Summary of implemented or synchronized changes.
   - `test_evidence`: Unit / E2E test execution output summary or confirmation.

3. **Output Format**:
   The skill returns a markdown payload with clearly identifiable sections:
   - `## TITLE`: The proposed PR title.
     - Implementation format: `feat(<change-name>): <concise title> (Addresses #<num>)`
     - Documentation format: `docs(<change-name>): close and sync OpenSpec specs (Ref #<num>)`
   - `## BODY`: The complete markdown description including:
     - Summary of changes
     - Issue reference (e.g. `Addresses #<num>`)
     - OpenSpec change reference
     - Test and verification evidence
     - Complexity and review notes (if applicable)
