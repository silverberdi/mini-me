import { api } from "./api_client.js";
export const discoverActions = (runId) => api.actions(runId);
export const executeAction = (runId, actionType, extra = {}) => api.execute(runId, { run_id: runId, action_type: actionType, expected_run_updated_at: extra.expected_run_updated_at, idempotency_key: crypto.randomUUID(), parameters: extra.parameters || {} });
