## Context

See `proposal.md` for the incident and intended outcome. On current `main`, the Change for Issue #366 is archived and its PostgreSQL listener publishes scheduler-originated `run.transition` plus `run.resync` through the existing authenticated SSE endpoint. However, `PostgresOrchestrationRunRepository.save` currently calls `notify_run_transition` only when `current_stage` changes. Gate creation/replacement is persisted through `update_stop_outcome`, which updates `stop_outcome`, `human_gate`, and `stop_details` without publishing a PostgreSQL notification. A gate raised during the same workflow stage therefore does not reach the API listener or browser automatically. `RefreshService` listens to `run.transition` and `run.resync`, refreshes the authoritative Runs projection on those events, and refreshes after EventSource opens. The API's gate-response path may publish `human.gate`, but the browser does not subscribe to it; gate visibility must continue to derive from the durable Run projection, not from an event payload.

The coordinator persists the current gate in `stop_details.human_payload`, and the Run API projects that payload. `TrabajoActualComponent` reads the original `question` and `options`, has an optional Spanish explanation path, and selects `response_text`, then `label`, then `id`. Thus translated labels must not take precedence over the original response value.

## Goals / Non-Goals

**Goals:**
- Give every active gate a clear Spanish operator-facing question and choice label while retaining exact source text, source type, stable option identity, and existing audit history.
- Show and recover the active gate through the Issue #366 SSE/API path, extended to notify on gate lifecycle changes even when `current_stage` is unchanged.
- Keep response authorization and current-gate resolution semantics unchanged.
- Prove the scheduler-to-browser flow with PostgreSQL and separate API/scheduler processes.

**Non-Goals:**
- Rebuild the Issue #366 event bridge, add a second event channel, periodic polling, a translation service, another database/table, or a gate workflow.
- Translate or rewrite the value submitted to resolve a native OpenSpec option.
- Change the Boxio Run, other Boxio Issues, CI/CD, or production deployment.

## Decisions

1. **Keep source and presentation together in the existing active gate payload.** Add Spanish presentation fields for the question and each option next to their exact original values and source metadata. Existing deterministic gate constructors provide Spanish text when authoring system-owned prompts. For agent/OpenSpec-originated prompts, the producing workflow supplies the Spanish rendering alongside the source content as part of the same handoff; mini me does not make a second translation-agent call or interpret the choice. The original question and native option remain unchanged and available in the operator view and audit payload.
   - **Alternative considered:** replace the original strings with Spanish. Rejected because the governing contract requires faithful preservation of native OpenSpec questions/options and their provenance.
   - **Alternative considered:** issue a separate translation request after a gate is raised. Rejected because it adds an agent invocation, latency, cost, failure mode, and a new action before the operator can see a gate.

2. **Use Spanish only for rendering; submit the stable original value.** The UI renders the Spanish field as the primary label and shows the exact source wording alongside it whenever it differs. Option selection uses the original `response_text` or stable `id`; if neither is present, it uses the original `label`. It never sends the Spanish display field as the resolution response. No new authorization meaning is inferred from translated text.
   - **Alternative considered:** send the localized label as free-text response. Rejected because it could fail to match a native choice or accidentally change an authorization.

3. **Extend the existing transactional notification for gate lifecycle changes.** The canonical PostgreSQL Run writers SHALL publish the existing bounded Run notification when the stage changes or when the active gate changes from absent to present, is replaced by a different active `gate_id`, or is resolved. In particular, `update_stop_outcome` SHALL notify when it persists those gate changes even if `current_stage` is unchanged. PostgreSQL delivers the notification only after the transaction commits; rollback emits none. The API listener relays it using the existing `run.transition` SSE event, and `RefreshService` re-reads the authoritative Runs projection. The notification contains no question, options, or provider text. No new SSE type or `human.gate` subscription is needed.
   - **Alternative considered:** rely on stage-change notifications alone. Rejected because a gate can be created or resolved while `current_stage` remains the same, leaving the PWA stale until another refresh.
   - **Alternative considered:** render the event's gate payload directly or add another gate event stream. Rejected because it duplicates or bypasses the authoritative Run projection and expands the event contract unnecessarily.

4. **Reuse existing JSON persistence and audit.** Store presentation fields inside the current `stop_details.human_payload`; keep exact original content and resolved-gate history as-is. No schema migration is expected. Keep the event payload limited to identifiers/status as already specified by Issue #366; never broadcast question text or options through PostgreSQL notifications.

5. **Exercise same-stage gate notification and the real path without deployment.** Extend the existing PostgreSQL-backed E2E fixture to persist a `HUMAN_REQUIRED` gate from an independent scheduler process without changing `current_stage`, observe the PostgreSQL notification and API SSE event, then read the gate from the authoritative Runs projection through the browser. Select a Spanish label and verify the exact original option value is submitted and the durable gate then resolves. Also cover gate replacement, rollback/no-op behavior, reconnect, and refresh with the same active gate. Use the repository's test PostgreSQL service; production deployment remains the project's CI/CD responsibility.

## Risks / Trade-offs

- **[Risk] A Spanish rendering could distort a native decision.** → Keep the source text visible, identify it as original, preserve source metadata, and submit only the original stable response value.
- **[Risk] A producer omits Spanish presentation data.** → Make the gate producer's contract require the Spanish presentation in the same handoff; the browser must not fabricate a translation or substitute a different option. Keep the gate visible with its source wording and an explicit Spanish notice until a valid presentation is available.
- **[Risk] Notification publication is missed on one of the gate persistence paths.** → Cover both `save` and `update_stop_outcome` writers with same-stage PostgreSQL integration cases for gate creation, replacement, resolution, rollback, and no-op updates.
- **[Risk] An event arrives before the browser can fetch the Run.** → Keep the observation stale until the authoritative projection succeeds; rely on the existing reconnect/resync behavior rather than trusting event data.
- **[Risk] A resolved gate is returned from stale state.** → Render only the gate identified as active by the current Runs projection; remove it only after a successful authoritative refresh confirms resolution.

## Migration Plan

No database migration, new dependency, service, or production deployment is planned. Add optional Spanish presentation fields to the existing JSON gate payload and preserve compatibility with historical records that contain only original text. Existing older gates remain readable with their original content; new/updated gate producers must include the Spanish presentation before the gate is presented as localized. Rollback is the normal code rollback through the repository's CI/CD; PostgreSQL records remain compatible because no existing keys are removed or reinterpreted.
