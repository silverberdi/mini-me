## 1. SRE Unblocker and Watchdog

- [x] 1.1 Add the canonical `minime-sre-unblocker` skill with the three initial playbooks: evidence-proven non-blocking PF-03 fallback, configured MCP OAuth refresh after 401, and proven orphan lock recovery; include idempotency, credential secrecy, stop conditions, and preserved human authority.
- [x] 1.2 Extend the existing Watchdog invocation path to call the configured SRE Unblocker through a read-only `thinking` profile only for eligible blockers and route actions through existing recovery authorities.
- [x] 1.3 Append sanitized, idempotent intervention attempt/resolution/escalation stage events; keep prior event facts unchanged and current diagnosis separate.
- [x] 1.4 Add focused unit and PostgreSQL integration coverage for all three playbooks, failed/ambiguous recovery, original gate question/options preservation, duplicate event delivery, and immutable event history (`pytest tests/test_watchdog_service.py tests/test_watchdog_postgres_e2e.py tests/test_watchdog_worktree_recovery.py tests/test_mcp_oauth.py`).

## 2. Autonomy and Mejora Continua

- [x] 2.1 Extend autonomy projection and Dashboard response to distinguish clean completion, autonomous recovery, operator-needed, and unverified outcomes while retaining current aggregate and no-data semantics.
- [x] 2.2 Link evidence-supported SRE skill/playbook improvement proposals to source events in the existing Mejora Continua flow without creating GitHub Issues automatically.
- [x] 2.3 Add pertinent telemetry and feed tests for all outcome categories, missing/conflicting evidence, and supported versus unsupported recurrence (`pytest tests/test_temporal_multiseries_telemetry.py tests/test_watchdog_service.py`).

## 3. Contract and real workflow evidence

- [x] 3.1 Update `docs/CONTRATO_RECTOR.md` to v2.1, `docs/METRICS.md`, `docs/RECONCILIACION_LEGADO.md`, `README.md`, and `AGENTS.md` so the governing contract and its entry points agree on bounded SRE authority, preserved human gates, and intervention evidence.
- [x] 3.2 Add a real PostgreSQL-backed orchestration E2E proving the configured role invocation, an eligible recovery and its observed effect, immutable event persistence, and operator escalation for a reserved or ambiguous decision; keep verification scoped to the pertinent Run/Watchdog E2E spec.
- [x] 3.3 Extend the independent reviewer guidance to compare implementation and persisted evidence against the skill allowlist and the exact candidate, including rejection of model self-report as proof.
- [x] 3.4 Run OpenSpec validation and the focused tests listed above; record actual command results and the immutable candidate SHA in the normal Apply/Verify evidence.
