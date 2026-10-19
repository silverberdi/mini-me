from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

LAYOUT = Path(__file__).parents[1] / "src/minime/static/js/desktop_pane_layout.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for layout test")
def test_desktop_layout_is_scoped_bounded_and_ignored_on_mobile() -> None:
    script = r"""
const fs = require('node:fs');
const { webcrypto } = require('node:crypto');
globalThis.crypto = webcrypto;
const handlers = new Map();
const stored = new Map();
const gridClasses = new Set();
const styleValues = new Map();
let desktop = true;
const master = { getBoundingClientRect: () => ({ width: 480 }) };
const grid = {
  clientWidth: 1200,
  classList: { toggle: (name, value) => value ? gridClasses.add(name) : gridClasses.delete(name) },
  querySelector: () => master,
  style: { setProperty: (key, value) => styleValues.set(key, value), removeProperty: (key) => styleValues.delete(key) },
};
const node = (id) => ({ hidden: false, textContent: '', attrs: {}, addEventListener: (name, cb) => handlers.set(`${id}:${name}`, cb), setAttribute: (key, value) => node(id).attrs[key] = value, setPointerCapture: () => {} });
const separator = node('separator');
const collapse = node('collapse');
const reset = node('reset');
const controls = node('controls');
globalThis.document = {
  querySelector: () => grid,
  getElementById: (id) => ({ paneSeparator: separator, collapseMasterPane: collapse, resetPaneLayout: reset }[id]),
};
globalThis.window = { matchMedia: () => ({ get matches() { return desktop; }, addEventListener() {} }), addEventListener() {} };
globalThis.localStorage = { getItem: (key) => stored.get(key) || null, setItem: (key, value) => stored.set(key, value), removeItem: (key) => stored.delete(key) };
const source = fs.readFileSync(process.argv.at(-1), 'utf8');
(async () => {
  const { initDesktopPaneLayout } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
  // Include the wrapper lookup used by the module.
  document.querySelector = (selector) => selector === '.content-split:not(.backlog-split)' ? grid : controls;
  await initDesktopPaneLayout('Operator@Example.test');
  if (!styleValues.has('--master-pane-width')) throw new Error('desktop default not applied');
  handlers.get('separator:keydown')({ key: 'ArrowRight', preventDefault() {} });
  const key = [...stored.keys()][0];
  if (!key || key.includes('Operator') || key.includes('Example')) throw new Error('identity was not hashed');
  if (!stored.has(key)) throw new Error('layout change not persisted');
  collapse.addEventListener = handlers.get('collapse:click');
  handlers.get('collapse:click')();
  if (!gridClasses.has('master-collapsed')) throw new Error('collapse failed');
  reset.addEventListener = handlers.get('reset:click');
  handlers.get('reset:click')();
  if (gridClasses.has('master-collapsed') || stored.has(key)) throw new Error('reset failed');
  desktop = false;
  await initDesktopPaneLayout('Operator@Example.test');
  if (styleValues.has('--master-pane-width')) throw new Error('desktop geometry leaked into mobile');
  console.log('desktop layout contract passed');
})().catch((error) => { console.error(error.stack); process.exitCode = 1; });
"""
    result = subprocess.run(
        [shutil.which("node") or "node", "-e", script, str(LAYOUT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "desktop layout contract passed" in result.stdout
