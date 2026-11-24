## 1. Backend SSE version emission

- [x] 1.1 In `src/minime/api/app.py`, update the `stream()` generator in `GET /api/v1/events` to emit an initial `app.version` event containing `version`, `commit_sha`, and `build_at` sourced from version metadata upon client connection.
- [x] 1.2 Add a focused backend unit test in `tests/test_realtime_sse_events.py` verifying that the `/api/v1/events` stream yields the `app.version` event on connection with valid JSON payload.

## 2. Frontend reactive update detection

- [x] 2.1 In `frontend/src/app/core/refresh.service.ts`, add an event listener for `app.version` in `connectEvents()` that compares the server's `commit_sha` with the client's loaded commit SHA.
- [x] 2.2 In `frontend/src/app/core/refresh.service.ts` and `frontend/src/app/app.component.ts`, trigger `swUpdate.checkForUpdate()` automatically upon detecting a version change or on stream reconnection (`onopen`) after a deployment restart, protected by a 30-second throttle.
- [x] 2.3 Ensure graceful offline handling: wrap all update checks with `swUpdate.isEnabled` and `try/catch` to guarantee zero unhandled rejections when disconnected or in dev mode.

## 3. Focused verification

- [x] 3.1 Run the focused backend tests (`.venv/bin/pytest tests/test_realtime_sse_events.py`) verifying event formatting and non-blocking emission.
- [x] 3.2 Run the focused frontend tests (`node --test frontend/tests/pwa-update-notification.test.mjs frontend/tests/pwa-reactive-components.test.mjs`) verifying reactive update detection and single-click activation.
