import { APIRequestContext, Page, expect } from '@playwright/test';

export const TEST_PROJECT_ID = 'e2e-project';
export const TEST_MODEL_ID = 'static-deepseek-chat';

/**
 * Resets the project to ACTIVE state via API request before or after tests.
 */
export async function resetProjectState(request: APIRequestContext, projectId = TEST_PROJECT_ID): Promise<void> {
  try {
    const res = await request.post(`/api/v1/projects/${encodeURIComponent(projectId)}/resume`);
    // Status 200 or 404 (if not yet seeded) is accepted gracefully
    if (res.ok()) {
      const data = await res.json();
      expect(data.status).toBe('ACTIVE');
    }
  } catch (err) {
    console.warn(`[E2E Helper] Project reset warning for ${projectId}:`, err);
  }
}

/**
 * Ensures the target provider model is enabled in the database catalog.
 */
export async function resetModelEnablement(request: APIRequestContext, modelId = TEST_MODEL_ID): Promise<void> {
  try {
    const catalogRes = await request.get('/api/v1/admin/providers/catalog');
    if (!catalogRes.ok()) return;

    const data = await catalogRes.json();
    const model = (data.models || []).find((m: any) => m.id === modelId);
    if (model && !model.is_enabled) {
      await request.patch(`/api/v1/admin/providers/models/${encodeURIComponent(modelId)}/enabled`, {
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
