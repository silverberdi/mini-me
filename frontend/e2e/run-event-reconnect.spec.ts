import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { resolve } from 'node:path';
import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import { setupAuthSession, waitForAppMounted } from './helpers';

const repositoryRoot = resolve(process.cwd(), '..');
const fixtureScript = 'tests/realtime_run_e2e_fixture.py';

function fixture(command: string, projectId: string, runId: string, stage?: string): string {
  const args = [fixtureScript, command, projectId, runId];
  if (stage) args.push(stage);
  return execFileSync(process.env['PYTHON'] || 'python3', args, {
    cwd: repositoryRoot,
    encoding: 'utf8',
    env: process.env,
  }).trim();
}

function observeRunSnapshots(page: Page, projectId: string, runId: string): string[] {
  const observedStages: string[] = [];
  page.on('response', async (response) => {
    const request = response.request();
    const url = new URL(response.url());
    if (
      request.method() !== 'GET' ||
      url.pathname !== '/api/v1/orchestration/runs' ||
      url.searchParams.get('project_id') !== projectId ||
      !response.ok()
    ) return;
    try {
      const runs = await response.json() as Array<{ run_id: string; current_stage: string }>;
      const run = runs.find((item) => item.run_id === runId);
      if (run) observedStages.push(run.current_stage);
    } catch {
      // Non-JSON or interrupted responses are not authoritative snapshots.
    }
  });
  return observedStages;
}

async function selectProject(context: BrowserContext, projectId: string): Promise<void> {
  await context.addInitScript((id) => {
    localStorage.setItem('minime_selected_project_id', id);
  }, projectId);
}

test('offline recovery and PostgreSQL listener recovery refresh the authoritative snapshot', async ({ browser }) => {
  test.skip(!process.env['MINIME_DATABASE_URL'], 'Requires the disposable PostgreSQL E2E database');
  const projectId = `issue366-${randomUUID()}`;
  const runId = randomUUID();
  const setup = JSON.parse(fixture('create', projectId, runId)) as { token: string };
  const firstContext = await browser.newContext();
  const secondContext = await browser.newContext();
  let firstPage: Page | null = null;
  let secondPage: Page | null = null;
  try {
    await Promise.all([
      setupAuthSession(firstContext, setup.token),
      setupAuthSession(secondContext, setup.token),
      selectProject(firstContext, projectId),
      selectProject(secondContext, projectId),
    ]);
    firstPage = await firstContext.newPage();
    secondPage = await secondContext.newPage();
    const firstStages = observeRunSnapshots(firstPage, projectId, runId);
    const secondStages = observeRunSnapshots(secondPage, projectId, runId);
    let firstEventConnections = 0;
    let secondEventConnections = 0;
    let firstEventStatus = 0;
    let secondEventStatus = 0;
    firstPage.on('request', (request) => {
      if (new URL(request.url()).pathname === '/api/v1/events') firstEventConnections += 1;
    });
    secondPage.on('request', (request) => {
      if (new URL(request.url()).pathname === '/api/v1/events') secondEventConnections += 1;
    });
    firstPage.on('response', (response) => {
      if (new URL(response.url()).pathname === '/api/v1/events') firstEventStatus = response.status();
    });
    secondPage.on('response', (response) => {
      if (new URL(response.url()).pathname === '/api/v1/events') secondEventStatus = response.status();
    });
    let firstNavigations = 0;
    let secondNavigations = 0;
    firstPage.on('framenavigated', (frame) => {
      if (frame === firstPage?.mainFrame()) firstNavigations += 1;
    });
    secondPage.on('framenavigated', (frame) => {
      if (frame === secondPage?.mainFrame()) secondNavigations += 1;
    });

    await Promise.all([firstPage.goto('/dashboard'), secondPage.goto('/dashboard')]);
    await Promise.all([waitForAppMounted(firstPage), waitForAppMounted(secondPage)]);
    await Promise.all([
      expect.poll(() => firstStages.includes('ADMITTED')).toBeTruthy(),
      expect.poll(() => secondStages.includes('ADMITTED')).toBeTruthy(),
      expect.poll(() => firstEventConnections > 0).toBeTruthy(),
      expect.poll(() => secondEventConnections > 0).toBeTruthy(),
      expect.poll(() => firstEventStatus === 200).toBeTruthy(),
      expect.poll(() => secondEventStatus === 200).toBeTruthy(),
    ]);
    const firstNavigationBaseline = firstNavigations;
    const secondNavigationBaseline = secondNavigations;

    await secondPage.waitForTimeout(300);
    await firstContext.setOffline(true);
    await firstPage.waitForTimeout(300);
    fixture('transition', projectId, runId, 'IMPLEMENTING');

    await expect.poll(() => secondStages.includes('IMPLEMENTING'), { timeout: 10000 }).toBeTruthy();
    await firstContext.setOffline(false);
    await expect.poll(() => firstStages.includes('IMPLEMENTING'), { timeout: 15000 }).toBeTruthy();

    const firstReadsBeforeRecovery = firstStages.length;
    const secondReadsBeforeRecovery = secondStages.length;
    fixture('recover-listener', projectId, runId);
    await Promise.all([
      expect.poll(() => firstStages.length > firstReadsBeforeRecovery, { timeout: 15000 }).toBeTruthy(),
      expect.poll(() => secondStages.length > secondReadsBeforeRecovery, { timeout: 15000 }).toBeTruthy(),
    ]);

    const firstReadsAfterRecovery = firstStages.length;
    const secondReadsAfterRecovery = secondStages.length;
    await firstPage.waitForTimeout(1500);
    expect(firstNavigations).toBe(firstNavigationBaseline);
    expect(secondNavigations).toBe(secondNavigationBaseline);
    expect(secondEventConnections).toBe(1);
    expect(firstStages).toHaveLength(firstReadsAfterRecovery);
    expect(secondStages).toHaveLength(secondReadsAfterRecovery);
    expect(firstStages.at(-1)).toBe('IMPLEMENTING');
    expect(secondStages.at(-1)).toBe('IMPLEMENTING');
  } finally {
    if (firstPage) await firstPage.close();
    if (secondPage) await secondPage.close();
    await firstContext.close();
    await secondContext.close();
    fixture('cleanup', projectId, runId);
  }
});
