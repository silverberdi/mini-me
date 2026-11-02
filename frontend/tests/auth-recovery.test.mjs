import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const app = await readFile(new URL("../src/app/app.component.ts", import.meta.url), "utf8");
const refresh = await readFile(new URL("../src/app/core/refresh.service.ts", import.meta.url), "utf8");

test("unauthenticated shell exposes the Google login action", () => {
  assert.match(app, /auth\.isLoaded\(\) && !auth\.session\(\)\.authenticated/);
  assert.match(app, /href=\"\/api\/v1\/auth\/google\/login\"/);
  assert.match(app, /Continuar con Google/);
});

test("refresh side effects start only after authentication succeeds", () => {
  assert.match(app, /this\.refresh\.start\(\);/);
  assert.match(refresh, /private started = false;/);
  assert.match(refresh, /if \(this\.started\) this\.setupTimer\(sec\);/);
  assert.doesNotMatch(refresh, /this\.connectEvents\(\);\s*\}/);
});
