## 1. Publish state changes through the existing SSE broker

- [x] 1.1 Publish `run.gate_acknowledged` when the existing endpoint accepts a human-gate response, before the asynchronous coordinator work completes; include only project and Run identity.
- [x] 1.2 Publish `project.pause_changed` after successful project and global pause/resume operations, identifying scope and affected project(s) without exposing unrelated project data.
- [x] 1.3 Publish `request.created`, `request.deactivated`, and `request.reactivated` after their corresponding existing endpoints succeed, with project and Request identities only.
- [x] 1.4 Add focused API tests proving the expected events are published for successful operations and no mutation event is published when an operation fails.

## 2. Consume events and acknowledge gate responses in the PWA

- [x] 2.1 Extend the existing `RefreshService` EventSource listeners to refresh authoritative state on the new gate, project, and Request events; preserve existing run/quota behavior and configured polling fallback.
- [x] 2.2 Add optimistic gate acknowledgement in Trabajo actual: hide the answered gate immediately, show processing feedback after acceptance, restore it on HTTP/transport failure, and reconcile it when the authoritative Run changes.
- [x] 2.3 Add focused frontend coverage for state-event refresh wiring and gate response success/failure behavior.

## 3. Verify end-to-end event delivery and frontend compilation

- [x] 3.1 Add an authenticated API-to-SSE integration test using the real `EventBroker` and existing endpoints to observe pause/Request events and prove gate acknowledgement is delivered before coordinator completion.
- [x] 3.2 Run the frontend test suite (`npm --prefix frontend test`) and production build (`npm --prefix frontend run build`); both must pass.
