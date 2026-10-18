import { api } from "./api_client.js";

// Keep Control Plane transport in one client while preserving its server-owned request contract.
export const discoverActions = (runId) => api.actions(runId);
export const executeAction = (runId, request) => api.execute(runId, request);
export const actionHistory = (runId) => api.history(runId);
