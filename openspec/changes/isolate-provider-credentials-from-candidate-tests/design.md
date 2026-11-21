## Context

See `proposal.md` for the motivation and scope. `CandidateTestResolver` selects native test commands, but those plans reach two execution paths: `ChecksRunner` for configured checks and some resolved commands, and a direct `asyncio.create_subprocess_exec` path in `NativeOrchestrationCoordinator` for other harnesses. The coordinator currently copies `os.environ` and removes only the operational database variables. `ChecksRunner` also starts from the host environment and removes database variables, then may restore a validated disposable database URL. `AgentProcessConfinement` already owns process environment preparation, while `CliAgentRunner` separately launches authorized model agents and must keep its provider credentials.

## Goals / Non-Goals

**Goals:**

- Prevent inherited host AI-provider credentials from reaching any candidate test process, independent of which supported test command strategy selected it.
- Keep the filtering at the existing process environment boundary and preserve runtime values plus explicitly authorized project-check values.
- Prove the actual child process cannot see host credential variables, while the needed runtime variables remain visible.

**Non-Goals:**

- Change provider authentication for thinking, execution, or review agents.
- Add a general project environment-variable configuration feature, alter command selection, or change Bubblewrap filesystem confinement.
- Add credential storage, test mocks, or paid-provider probes.

## Decisions

### Use one candidate-test environment sanitizer at existing spawn boundaries

Use the existing `AgentProcessConfinement` environment-preparation responsibility for a narrowly scoped candidate-test environment builder, and call it from both test subprocess launch paths. It starts empty and copies only an explicit baseline allowlist of operating-system and supported toolchain runtime variables. All other host variables are excluded, including provider credentials, wildcard API-key/secret names, and credentials with other names. `CandidateTestResolver` remains responsible for selecting commands; it does not become an environment-management component.

**Alternative considered:** Filter only inside `CandidateTestResolver`. Rejected because the resolver returns a plan and does not launch commands; configured checks and direct subprocess execution could bypass it.

**Alternative considered:** Filter independently in each runner. Rejected because duplicated security policy can drift between test paths.

### Keep explicit project-check values distinct from inherited host values

The baseline allowlist is explicit: `PATH`, `HOME`, `LANG`, `LC_ALL`, `LC_CTYPE`, `LC_MESSAGES`, `LANGUAGE`, `TMPDIR`, `TMP`, `TEMP`, `DOTNET_ROOT`, `DOTNET_CLI_HOME`, `NUGET_PACKAGES`, `NODE_PATH`, `PYTHONPATH`, `GOPATH`, `GOROOT`, `GOCACHE`, `GOMODCACHE`, `GOTOOLCHAIN`, `CARGO_HOME`, and `RUSTUP_HOME`. `ChecksRunner` continues to create its private `PYTHONPYCACHEPREFIX`, temporary paths, candidate-aware `PATH`, and `PYTHONPATH` after filtering. It may add `MINIME_DATABASE_URL` and `MINIME_EXPECTED_DATABASE` only for a check explicitly configured for disposable PostgreSQL and only after the existing database-name validation succeeds; the URL can come from the check's supported `database_url` field or the host's `MINIME_DATABASE_URL` source used by that validated flow. Do not introduce arbitrary per-project environment configuration. The direct coordinator path receives only the runtime baseline and removes Mini Me database settings.

### Leave authorized model execution unchanged

The sanitizer is used only at candidate test subprocess boundaries. Do not change `CliAgentRunner` provider setup or the environment used for authorized thinking, execution, and review agent invocations.

## Risks / Trade-offs

- **[An unrecognized test strategy bypasses filtering] →** Cover every `CandidateTestResolver` execution branch and both subprocess launch paths; run child-process regression tests through those paths.
- **[A supported toolchain needs a runtime variable not in the baseline] →** Add that specific non-secret runtime variable to the allowlist with a regression test; never fall back to copying the host environment.
- **[Filtering is mistakenly applied to model agents] →** Keep call sites restricted to candidate test launchers and add a regression asserting agent invocation setup remains unchanged.

## Migration Plan

No persisted data, API, or project configuration migration is required. Rollback is a source revert; it restores the previous inherited test environment behavior.

## Open Questions

None. The issue provides the provider-variable list, exception boundary, and test expectations.
