import { APIRequestContext, BrowserContext, Page, expect } from '@playwright/test';

export const TEST_PROJECT_ID = 'e2e-project';
export const TEST_MODEL_ID = 'static-deepseek-chat';
export const E2E_SESSION_TOKEN = 'e2e-session-token-32-chars-long-xxx';
const PRESERVED_E2E_RUN_IDS = new Set(['e2e-human-gate-run']);

/**
 * Ensures the browser context has the valid E2E session cookie installed.
 */
export async function setupAuthSession(
  context: BrowserContext,
  token = E2E_SESSION_TOKEN,
): Promise<void> {
  await context.addCookies([
    {
      name: 'minime_session',
      value: token,
      domain: '127.0.0.1',
      path: '/',
      httpOnly: false,
      secure: false,
      sameSite: 'Lax',
    },
  ]);
}

/**
 * Resets the project to ACTIVE state via API request before or after tests.
 */
export async function resetProjectState(request: APIRequestContext, projectId = TEST_PROJECT_ID): Promise<void> {
  if (projectId !== TEST_PROJECT_ID) {
    throw new Error(`E2E reset is restricted to ${TEST_PROJECT_ID}; received ${projectId}.`);
  }
  const headers = { Authorization: `Bearer ${E2E_SESSION_TOKEN}` };
  const runsResponse = await request.get(
    `/api/v1/orchestration/runs?project_id=${encodeURIComponent(TEST_PROJECT_ID)}&is_active=true`,
    { headers },
  );
  if (!runsResponse.ok()) {
    throw new Error(`Unable to inspect active E2E runs (${runsResponse.status()}): ${await runsResponse.text()}`);
  }
  const runs = await runsResponse.json();
  if (!Array.isArray(runs)) throw new Error('Active E2E run response is not a list.');
  for (const run of runs) {
    if (!run?.run_id || run.project_id !== TEST_PROJECT_ID || run.is_active !== true) {
      throw new Error('Active-run response contained an unexpected or incomplete E2E run identity.');
    }
    if (PRESERVED_E2E_RUN_IDS.has(run.run_id)) continue;
    if (run.active_job_id) {
      throw new Error(`Cannot reset ${TEST_PROJECT_ID}: run ${run.run_id} still has active job ${run.active_job_id}; left it untouched.`);
    }
    const cancelResponse = await request.post(
      `/api/v1/projects/${encodeURIComponent(TEST_PROJECT_ID)}/runs/${encodeURIComponent(run.run_id)}/cancel`,
      {
        headers,
        data: {
          reason: 'Reset residual run before isolated Playwright E2E.',
          idempotency_key: `playwright-reset-${run.run_id}-${Date.now()}`,
        },
      },
    );
    if (!cancelResponse.ok()) {
      throw new Error(`Unable to safely cancel E2E run ${run.run_id} (${cancelResponse.status()}): ${await cancelResponse.text()}`);
    }
    const cancellation = await cancelResponse.json();
    if (cancellation.status !== 'CANCELLED' || !['CLEANED', 'NOT_REQUIRED'].includes(cancellation.workspace_cleanup)) {
      throw new Error(`E2E run ${run.run_id} cancellation/cleanup was not confirmed: ${JSON.stringify(cancellation)}`);
    }
  }

  const remainingResponse = await request.get(
    `/api/v1/orchestration/runs?project_id=${encodeURIComponent(TEST_PROJECT_ID)}&is_active=true`,
    { headers },
  );
  if (!remainingResponse.ok()) {
    throw new Error(`Unable to verify E2E run cleanup (${remainingResponse.status()}): ${await remainingResponse.text()}`);
  }
  const remainingRuns = await remainingResponse.json();
  if (!Array.isArray(remainingRuns)) {
    throw new Error('Active-run response is not a list after the cleanup pass.');
  }
  for (const run of remainingRuns) {
    if (
      !run?.run_id ||
      run.project_id !== TEST_PROJECT_ID ||
      run.is_active !== true ||
      !PRESERVED_E2E_RUN_IDS.has(run.run_id) ||
      run.active_job_id
    ) {
      throw new Error(`E2E project still has an unexpected active run after cleanup: ${JSON.stringify(run)}`);
    }
  }

  const resumeResponse = await request.post(
    `/api/v1/projects/${encodeURIComponent(TEST_PROJECT_ID)}/resume`, { headers },
  );
  if (!resumeResponse.ok()) {
    throw new Error(`Unable to resume ${TEST_PROJECT_ID} (${resumeResponse.status()}): ${await resumeResponse.text()}`);
  }
  const resumed = await resumeResponse.json();
  expect(resumed.status).toBe('RESUMED');
}

/**
 * Ensures the target provider model is enabled in the database catalog.
 */
export async function resetModelEnablement(request: APIRequestContext, modelId = TEST_MODEL_ID): Promise<void> {
  try {
    const catalogRes = await request.get('/api/v1/admin/providers/catalog', {
      headers: {
        Authorization: `Bearer ${E2E_SESSION_TOKEN}`,
      },
    });
    if (!catalogRes.ok()) return;

    const data = await catalogRes.json();
    const model = (data.models || []).find((m: any) => m.id === modelId);
    if (model && !model.is_enabled) {
      await request.patch(`/api/v1/admin/providers/models/${encodeURIComponent(modelId)}/enabled`, {
        headers: {
          Authorization: `Bearer ${E2E_SESSION_TOKEN}`,
        },
        data: {
          is_enabled: true,
          version: model.version,
        },
      });
    }
  } catch (err) {
    console.warn(`[E2E Helper] Model reset warning for ${modelId}:`, err);
  }
}

/**
 * Waits for the Angular application to be fully mounted in the DOM.
 */
export async function waitForAppMounted(page: Page): Promise<void> {
  await expect(page.locator('app-root')).toBeVisible({ timeout: 10000 });
}
