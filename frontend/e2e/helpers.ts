import { APIRequestContext, BrowserContext, Page, expect } from '@playwright/test';

export const TEST_PROJECT_ID = 'e2e-project';
export const TEST_MODEL_ID = 'static-deepseek-chat';
export const E2E_SESSION_TOKEN = 'e2e-session-token-32-chars-long-xxx';

/**
 * Ensures the browser context has the valid E2E session cookie installed.
 */
export async function setupAuthSession(context: BrowserContext): Promise<void> {
  await context.addCookies([
    {
      name: 'minime_session',
      value: E2E_SESSION_TOKEN,
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
  try {
    const res = await request.post(`/api/v1/projects/${encodeURIComponent(projectId)}/resume`, {
      headers: {
        Authorization: `Bearer ${E2E_SESSION_TOKEN}`,
      },
    });
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
