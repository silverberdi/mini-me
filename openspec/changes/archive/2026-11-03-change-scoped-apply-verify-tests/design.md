## Context

See `proposal.md` for the motivation. The existing `_run_automated_tests(worktree_path)` invokes `python -m pytest -q`; the orchestration path already persists the returned test evidence. The `openspec-native-apply-and-verify` delta replaces the complete-suite gate with a focused test gate. The design preserves the current runner and stage flow and does not modify CI/CD.

## Goals / Non-Goals

**Goals:**
- Resolve a deterministic, bounded set of tests from candidate changes visible to Git, including uncommitted and untracked files produced during Apply.
- Include tests changed or added by the candidate and tests relevant to changed executable files.
- Preserve the actual command, exit code, and runner output through the existing test evidence path.

**Non-Goals:**
- Configure or run project CI/CD, or change its complete-suite pre-merge gate.
- Change Apply recovery (#259), code review (#261), Verify workflow dispatch, or other orchestration stages.
- Build a general-purpose dependency-analysis framework or add a test-selection dependency.

## Decisions

### Determine changed files from the candidate, not the agent's report

Use the candidate's configured base branch and Git state to collect paths changed between the base and candidate, plus staged, unstaged, and untracked paths in the worktree. Normalize and deduplicate the paths, and ignore deleted paths when resolving test files. If Git cannot establish the candidate change set, preserve the failure as test-selection evidence and fail the gate; do not substitute `pytest -q`.

The base reference is supplied by the existing orchestration context when invoking `_run_automated_tests`; this avoids assuming `main` for projects with another configured base branch. No new persisted state is needed.

### Map changed files to a bounded pytest selection

Build selectors from:
1. Every added or modified test file in the candidate change.
2. Existing tests whose module/file convention maps to a changed executable file (mirrored package path or matching `test_<module>`/`<module>_test` name).
3. Existing tests with direct imports of the changed Python module, where the repository's test files expose that relationship.

Deduplicate selectors and pass only those paths to the existing pytest invocation. Do not add a whole-suite fallback when no mapping is found. An empty selection or pytest's no-tests-collected result remains a failed/non-passing gate, consistent with the existing exit-code handling. The mapping rules and their limitations are documented in this design and reflected in focused tests.

This bounded convention-based mapping is chosen over running the full suite and filtering afterward (which still executes unrelated failures and incurs the full cost), and over a new coverage/dependency plugin (which adds a dependency and execution model not required by Issue #264). It may miss tests reached only through dynamic imports or indirect behavior not represented by file/module conventions; directly changed tests are always included, and the non-empty focused suite remains the evidence boundary.

### Build direct-import mappings in one pass

For each selection operation, visit every candidate pytest file once, parse its AST once, and have `_imported_modules` return the set of imported module names. Build an inverse `module → test paths` index from those sets. For each changed source module, use `import_index.get(module)` to retrieve its tests. Keep the existing path/name matching selectors and union their results with the import-index results; do not re-parse files per changed module. This makes import matching proportional to the number of test files plus changed modules and preserves the prior selection semantics.

### Preserve runner evidence in the existing path

Keep the existing subprocess runner and caller. Extend its evidence text with the exact argument vector rendered as a reproducible command and the process exit code, followed by captured stdout and stderr. The caller continues persisting this coordinator-observed evidence; the agent's description is not used to establish the test result. Do not add a database field or separate evidence subsystem.

### Verify selection without running unrelated tests

Add focused coordinator tests that use a temporary Git repository and deterministic test files to verify changed-file discovery, changed-test inclusion, source-to-test mapping, exclusion of unrelated test files, empty selection failure, and exact command/exit/output evidence. These tests validate orchestration and selection; they are not represented as real-agent E2E evidence. No full project suite is added to the mini me Apply/Verify path by this change.

## Risks / Trade-offs

- [Static/convention mapping can miss dynamically imported or indirectly affected tests] → Include changed test files unconditionally, combine path and direct-import mapping, document the limitation, and keep the set bounded rather than silently running the whole suite.
- [An incorrect base reference can omit changed files] → Use the configured candidate base branch and fail closed with captured Git-selection error when the comparison cannot be established.
- [A change may have no resolvable tests] → Treat empty/no-tests-collected as non-passing and preserve the diagnostic; do not convert it into a full-suite run.

## Migration Plan

No data migration is required. The existing caller continues consuming the result and persisting evidence; the invocation supplies the configured base branch. Rollback consists of reverting the focused selector and restoring the previous test invocation, without changing stored records or CI/CD.

## Open Questions

None.
