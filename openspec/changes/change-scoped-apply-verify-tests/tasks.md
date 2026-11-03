## 1. Select tests for the candidate change

- [ ] 1.1 Pass the configured candidate base branch into test selection and collect changed paths from Git's base-to-candidate diff plus staged, unstaged, and untracked worktree files; fail closed when the change set cannot be determined.
- [ ] 1.2 Select added or modified test files and map changed executable files to tests using mirrored paths, test-module naming conventions, and direct imports; deduplicate selectors and never fall back to the complete suite.
- [ ] 1.3 Treat an empty selection or no-tests-collected result as non-passing evidence, without introducing a new stage or persistent state.

## 2. Preserve focused test execution evidence

- [ ] 2.1 Run only the selected test paths through the existing pytest subprocess and preserve the exact command, exit code, stdout, and stderr through the current coordinator evidence path.
- [ ] 2.2 Add focused coordinator tests using a temporary Git repository to verify changed-path discovery, own-test inclusion, source-to-test mapping, unrelated-test exclusion, and empty-selection behavior.
- [ ] 2.3 Verify focused tests assert the executed command and captured process output/status, and that the existing Apply/Verify gate consumes the focused result without changing other stages or CI/CD.
