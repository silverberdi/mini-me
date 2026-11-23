# Removal Ledger

| Surface | Decision | Evidence |
| --- | --- | --- |
| `dashboard.component.ts` `runs().slice(0, 5)` autonomy/time projection | Retired | `rg -n "slice\\(0, 5\\)|autonomy_percent" frontend/src/app/features/dashboard frontend/e2e tests` returns no active Dashboard caller after migration. |
| `dashboard-cost-chart.ts` and provider cost cards | Retained | The existing ledger-backed provider/model summary remains an active Dashboard consumer and regression coverage; it is not the superseded five-run authority. |
| `dashboard_service.py:get_cost_projection` | Retained | Existing verified settlement authority is reused by the temporal cost projection; no parallel pricing source introduced. |
| `RefreshService` dashboard read | Migrated | One authenticated `/api/v1/dashboard/overview` response now carries `temporal_telemetry` for all three dimensions. |
| Durable runs, stage events, efficiency metrics and ledger rows | Retained | They remain authoritative sources and historical records; no data rewrite or destructive migration is in scope. |

Static verification command:

```text
rg -n "slice\\(0, 5\\)|autonomy_percent|chartPoints" frontend/src/app/features/dashboard src/minime/services tests frontend/e2e
```
