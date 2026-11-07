import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../src/app/features/trabajo-actual/trabajo-actual.component.ts', import.meta.url), 'utf8');

test('complexity presentation is rendered in the pipeline stepper', () => {
  assert.match(source, /aria-label="Complejidad asignada"/);
  assert.match(source, /\{\{ assignedComplexity\(\) \}\}/);
  assert.match(source, /\*ngIf="complexityEvidence\(\)"/);
  assert.match(source, /\{\{ complexityEvidence\(\) \}\}/);
});

test('assigned complexity reads only from the selected Run stop_details', () => {
  const method = source.match(/assignedComplexity\(\):[\s\S]*?\n  \}/)?.[0];
  assert.ok(method, 'assignedComplexity helper exists');
  assert.match(method, /this\.targetRun\(\)\?\.stop_details\?\.\['complexity'\]/);
  assert.match(method, /complexity === 'high'/);
  assert.match(method, /complexity === 'moderate'/);
  assert.match(method, /complexity === 'low'/);
  assert.match(method, /'Pendiente'/);
  assert.doesNotMatch(method, /moderate.*fallback|fallback.*moderate/i);
});

test('all valid levels are covered without inventing an unknown level', () => {
  const method = source.match(/assignedComplexity\(\):[\s\S]*?\n  \}/)?.[0];
  assert.ok(method);
  const validLevels = method.match(/complexity === '(high|moderate|low)'/g) || [];
  assert.deepEqual(validLevels.sort(), [
    "complexity === 'high'",
    "complexity === 'low'",
    "complexity === 'moderate'",
  ].sort());
  assert.match(method, /: 'Pendiente'/);
});

test('evidence is read from stop_details and absent evidence is omitted', () => {
  const method = source.match(/complexityEvidence\(\):[\s\S]*?\n  \}/)?.[0];
  assert.ok(method, 'complexityEvidence helper exists');
  assert.match(method, /this\.targetRun\(\)\?\.stop_details\?\.\['complexity_evidence'\]/);
  assert.match(method, /evidence === null \|\| evidence === undefined \|\| evidence === ''/);
  assert.match(method, /JSON\.stringify\(evidence\)/);
});

test('high complexity only communicates the existing review requirement', () => {
  assert.match(source, /isHighComplexity\(\)/);
  assert.match(source, /requiere revisión de propuesta y revisión de código/);
  assert.match(source, /esta indicación no confirma que esas revisiones ya hayan ocurrido/);
  assert.doesNotMatch(source, /recalcular|evaluación nueva|asignar.*complejidad/i);
});

test('complexity change does not add a backend contract or mutation', () => {
  const section = source.slice(source.indexOf('aria-label="Complejidad asignada"'), source.indexOf('<!-- HUMAN_REQUIRED'));
  assert.doesNotMatch(section, /api\.post|api\.put|api\.patch|api\.delete|\(click\)=/);
  assert.match(source, /readonly targetRun = computed/);
});
