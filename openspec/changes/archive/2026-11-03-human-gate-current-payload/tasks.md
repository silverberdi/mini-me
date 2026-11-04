## 1. Persist the payload for each scoped gate

- [x] 1.1 Update proposal/code-review and Apply escalation writers to persist the current gate identity, question, and options while preserving existing authorization and resume behavior.
- [x] 1.2 Persist the PR1 acknowledgement and physical-validation payloads at gate entry, replacing any prior active payload in the same Run update.
- [x] 1.3 Clear the active payload only when the existing backend flow durably confirms that gate's resolution; retain unresolved payloads during refused or uncertain responses.

## 2. Expose and render the active payload

- [x] 2.1 Update the Run API projection to use only the active durable payload and stop deriving current gate content/status from resolved Explore/Propose checkpoints.
- [x] 2.2 Update Trabajo actual gate detection and question/options rendering to read the active durable payload only, preserving the existing authorized response control.

## 3. Verify current-gate behavior

- [x] 3.1 Add focused coordinator/API tests for each scoped gate, payload replacement, durable resolution, and rejection of stale checkpoint fallback.
- [x] 3.2 Add frontend tests confirming the later gate's question/options render after refresh and that the existing response submission remains available.
- [x] 3.3 Run an integration/E2E path through persisted Run state, the real Run API projection, and the PWA response flow; record the observed gate payload and response result.
