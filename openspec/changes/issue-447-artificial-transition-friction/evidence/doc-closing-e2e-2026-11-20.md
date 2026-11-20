# DOC_CLOSING E2E evidence

- Environment: PostgreSQL `minime_test` on `192.168.0.194`; temporary repository under `/private/tmp`; no production issue or repository used.
- Candidate: base `7976ccfb74786c1dd23226a12c9b7cfa679ed5a2`; SHA-256 of the implementation/test diff at execution: `f2a1f6db23c1ee4f2971b855fff9d5fc428ed47a56dee0d877968361cee4cd96`.
- Synthetic Run: `60fb6064-bf91-446d-bd40-494c567004a5`; project `e2e447-caa21310ce47`; change `issue-447-doc-closing-e2e-caa21310ce47`.
- Invocations: native Sync and native Archive through the configured Codex CLI profile (`gpt-5.6-luna`, low effort); both processes exited 0 and produced observable effects. Archive used `--yes --skip-specs`.
- Persistence: PostgreSQL recorded `STAGE_INVOCATION_STARTED`, `STAGE_INVOCATION_PROCESS_STARTED`, and `STAGE_INVOCATION_COMPLETED` for both operations. The Run transitioned from `DOC_CLOSING` to `PR2_PENDING`.
- Git: native Sync created `openspec/specs/doc-closing-e2e/spec.md`; native Archive created exactly one archive. DOC_CLOSING committed both under `4c570906a7e9309a5b87197739633b06b536b8a5` (`docs(issue-447-doc-closing-e2e-caa21310ce47): sync specs and archive change`); `openspec/` was clean afterward.
- Cleanup: the synthetic project and Run were removed; a PostgreSQL query confirmed zero project rows for the fixture. The temporary repository, SSH tunnel, and runtime directory were removed.
- Verification note: `CliAgentRunner` returned null provider/model fields in its in-memory result metadata, although the fixture selected the Codex profile and both native CLI workflows completed. This E2E validates the DOC_CLOSING behavior and durable transition; it does not claim those provider/model fields are persisted in stage events.
