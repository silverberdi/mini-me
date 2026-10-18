from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

SERVICE_WORKER = Path(__file__).parents[1] / "src/minime/static/sw.js"
STATIC_ROOT = Path(__file__).parents[1] / "src/minime/static"


def test_service_worker_allowlist_contains_only_existing_shell_resources() -> None:
    source = SERVICE_WORKER.read_text(encoding="utf-8")
    match = re.search(r"const SHELL_ASSETS = \[(.*?)\];", source, re.DOTALL)
    assert match is not None
    assets = re.findall(r'"([^\"]+)"', match.group(1))
    assert assets
    for asset in assets:
        if asset in {"/", "/dashboard"}:
            continue
        assert asset.startswith("/static/")
        assert (STATIC_ROOT / asset.removeprefix("/static/")).is_file(), asset


def test_service_worker_allowlists_the_complete_live_module_import_graph() -> None:
    source = SERVICE_WORKER.read_text(encoding="utf-8")
    match = re.search(r"const SHELL_ASSETS = \[(.*?)\];", source, re.DOTALL)
    assert match is not None
    assets = set(re.findall(r'"([^\"]+)"', match.group(1)))
    pending = [STATIC_ROOT / "js" / "app.js"]
    visited: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        module_source = path.read_text(encoding="utf-8")
        for specifier in re.findall(r'from\s+["\']([^"\']+)["\']', module_source):
            if not specifier.startswith("."):
                continue
            dependency = (path.parent / specifier).resolve()
            assert dependency.is_relative_to(STATIC_ROOT.resolve())
            pending.append(dependency)
    for path in visited:
        asset = "/static/" + path.relative_to(STATIC_ROOT).as_posix()
        assert asset in assets, f"live module missing from offline shell allowlist: {asset}"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for SW contract test")
def test_service_worker_caches_only_allowlisted_static_gets(tmp_path: Path) -> None:
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const listeners = new Map();
const stores = new Map();
const touched = [];
const self = {
  location: { origin: 'https://mini.test' },
  clients: { claim: async () => {} },
  addEventListener: (name, callback) => listeners.set(name, callback),
  skipWaiting: async () => {},
};
const cacheApi = {
  async open(name) {
    if (!stores.has(name)) stores.set(name, new Map());
    const store = stores.get(name);
    return {
      addAll: async (paths) => paths.forEach((path) => store.set(path, new Response('shell'))),
      put: async (request, response) => { touched.push(['put', request.url]); store.set(request.url, response); },
      match: async (request) => store.get(request.url),
    };
  },
  async keys() { return [...stores.keys()]; },
  async delete(key) { return stores.delete(key); },
  async match(request) {
    for (const store of stores.values()) if (store.has(request.url)) return store.get(request.url);
  },
};
const context = {
  self,
  caches: cacheApi,
  URL,
  Request,
  Response,
  Promise,
  fetch: async (request) => { touched.push(['fetch', request.url]); return new Response('network'); },
};
vm.runInNewContext(fs.readFileSync(process.argv.at(-1), 'utf8'), context);

async function dispatch(request) {
  let responsePromise;
  const pending = [];
  listeners.get('fetch')({ request, respondWith: (promise) => { responsePromise = promise; }, waitUntil: (promise) => pending.push(promise) });
  if (responsePromise) await responsePromise;
  await Promise.all(pending);
  return Boolean(responsePromise);
}

(async () => {
  stores.set('minime-pwa-shell-v1', new Map([['old', new Response('old')]]));
  stores.set('other-app-cache', new Map([['keep', new Response('keep')]]));
  let activation;
  listeners.get('activate')({ waitUntil: (promise) => { activation = promise; } });
  await activation;
  if (stores.has('minime-pwa-shell-v1') || !stores.has('other-app-cache')) throw new Error('cache cleanup escaped owned namespace');

  let writes = 0;
  const allowed = await dispatch(new Request('https://mini.test/static/css/pwa.css'));
  if (!allowed) throw new Error('allowlisted static GET was not handled');
  writes = touched.filter(([kind]) => kind === 'put').length;

  const before = touched.length;
  for (const request of [
    new Request('https://mini.test/api/v1/dashboard/overview'),
    new Request('https://mini.test/api/v1/auth/me'),
    new Request('https://mini.test/api/v1/control-plane/actions/execute', { method: 'POST' }),
    new Request('https://other.test/static/css/pwa.css'),
    new Request('https://mini.test/static/not-allowlisted.txt'),
    new Request('https://mini.test/static/css/pwa.css?user=data'),
  ]) {
    if (await dispatch(request)) throw new Error(`non-static request was intercepted: ${request.url}`);
  }
  if (touched.length !== before || writes !== 1) throw new Error('non-allowlisted request touched cache/network worker path');
  console.log('service worker contract passed');
})().catch((error) => { console.error(error.message); process.exitCode = 1; });
"""
    result = subprocess.run(
        [shutil.which("node") or "node", "-e", script, str(SERVICE_WORKER)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "service worker contract passed" in result.stdout
