# 022 — F10 Asynchronous Decoupling, Telemetry & Real-Time Observability E2E Evidence

## Execution Metadata
- **Change Identifier**: `req-207-f10-desacoplamiento-asincrono-telemetria`
- **Candidate Commit SHA**: `f699c579b3f448454ad53b8ef71d5666fb41d6ac`
- **Execution Timestamp**: `2026-11-01T12:19:42.786637+00:00`
- **Verification Environment**: Ubuntu Linux 24.04 LTS (x86_64) on host `192.168.0.194`
- **Governing Canonical Contract**: Contrato Rector v1.3

---

## 1. Asynchronous Run Acceptance (HTTP 202 Accepted)

The API validates caller intent and admissions synchronously, returning an immediate `HTTP 202 Accepted` status with a durable `operation_id` to eliminate proxy timeouts during long-running agent workflows.

- **Request**: `POST /api/v1/projects/mini-me/requests/run`
- **Status Code**: `202 Accepted`
- **Response Payload**:
```json
{
  "status": "ACCEPTED",
  "operation_id": "895986d0-29ed-4174-bc69-450b0a16b306",
  "run_id": null,
  "message": "Run accepted for bounded background execution."
}
```

---

## 2. Live Provider Quota Telemetry (60s Bounded Cache)

Provider capacity is observed through provider strategies, recording real five-hour rolling windows, account/model identities, and explicit unknown states without fabricated values.

- **Request**: `GET /api/v1/providers/quotas`
- **Status Code**: `200 OK`
- **Response Payload**:
```json
{
  "observed_at": "2026-11-01T12:19:42.786637+00:00",
  "providers": [
    {
      "provider": "antigravity",
      "state": "AVAILABLE",
      "observed_at": "2026-11-01T12:19:37.593119+00:00",
      "source": "agy_print_usage",
      "remaining_percent": 96.1,
      "balance": null,
      "currency": null,
      "reset_at": "2026-11-01T17:06:40Z",
      "window": "5h",
      "account_id": "efb24eec902c74f90c633f32cbd34100e8309764e521c71b0b1177d61796bddc",
      "model_id": "Gemini Models",
      "status_label": "Normal",
      "stale": false,
      "reason": null
    },
    {
      "provider": "codex",
      "state": "AVAILABLE",
      "observed_at": "2026-11-01T12:19:40.757808+00:00",
      "source": "codex_app_server_rate_limits_read",
      "remaining_percent": 100.0,
      "balance": null,
      "currency": null,
      "reset_at": "2026-11-01T17:19:42+00:00",
      "window": "5h",
      "account_id": "00d41d1d-a324-413c-b1f0-c63eafc7b411",
      "model_id": "codex",
      "status_label": "Normal",
      "stale": false,
      "reason": null
    },
    {
      "provider": "deepseek",
      "state": "AVAILABLE",
      "observed_at": "2026-11-01T12:19:42.247773+00:00",
      "source": "deepseek_account_balance",
      "remaining_percent": null,
      "balance": 21.57,
      "currency": "USD",
      "reset_at": null,
      "window": null,
      "account_id": "070790f015df88a7fa34d2d0c1f76ee223165438b5728a03c0571542e4e39a36",
      "model_id": "deepseek-chat",
      "status_label": "Normal",
      "stale": false,
      "reason": null
    }
  ]
}
```

---

## 3. Real-Time Event Streaming (Server-Sent Events)

The system exposes an SSE stream providing immediate fan-out notifications for run stage transitions, human gate requirements, and quota updates to connected web clients.

- **Request**: `GET /api/v1/events`
- **Status Code**: `200 OK`
- **Response Content-Type**: `text/event-stream; charset=utf-8`
- **Cache-Control**: `no-cache`
- **X-Accel-Buffering**: `no`
- **Initial Stream Chunk**:
```
: connected


```

---

## 4. Frontend Production Build & Test Verification

- **Production Angular Build**: `ng build --configuration production` completed in 3.2s producing `dist/minime-frontend` with zero compiler warnings and clean schema validation.
- **Frontend Test Suite**: `node --test tests/*.test.mjs` completed with 4 passed, 0 failed.
- **Python Automated Suite**: 944 passed, 52 skipped across entire worktree.
- **Static Code Analysis**: `ruff check .` reported `All checks passed!`.
