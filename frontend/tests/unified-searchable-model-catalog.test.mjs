import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const sourceRoot = new URL('../src/app/', import.meta.url);
const proyectosSrc = fs.readFileSync(new URL('features/proyectos/proyectos.component.ts', sourceRoot), 'utf8');
const comboboxSrc = fs.readFileSync(new URL('shared/model-combobox.component.ts', sourceRoot), 'utf8');

test('ProyectosComponent has eliminated initial static models array in favor of authoritative backend catalog', () => {
  // Must NOT initialize with hardcoded static models
  assert.doesNotMatch(proyectosSrc, /availableModels:\s*\{\s*id:\s*string;[\s\S]*?=\s*\[\s*\{\s*id:\s*'deepseek\/deepseek-flash'/);
  assert.match(proyectosSrc, /availableModels:\s*ModelOption\[\]\s*=\s*\[\];/);
  assert.match(proyectosSrc, /isCatalogLoading\s*=\s*signal\(false\);/);
});

test('ProyectosComponent uses ModelComboboxComponent for all 4 project roles in creation and editing', () => {
  // Imported and declared in standalone imports
  assert.match(proyectosSrc, /import\s*\{\s*ModelComboboxComponent,\s*ModelOption\s*\}\s*from\s*'\.\.\/\.\.\/shared\/model-combobox\.component';/);
  assert.match(proyectosSrc, /imports:\s*\[[\s\S]*?ModelComboboxComponent[\s\S]*?\]/);

  // Combobox integrated for thinking, execution, independent_review, fallback in Create Modal
  assert.match(proyectosSrc, /<app-model-combobox[\s\S]*?label="Thinking \(Exploración\)"[\s\S]*?\[\(modelValue\)\]="newProjectProfiles\.thinking"/);
  assert.match(proyectosSrc, /<app-model-combobox[\s\S]*?label="Execution \(Código\)"[\s\S]*?\[\(modelValue\)\]="newProjectProfiles\.execution"/);
  assert.match(proyectosSrc, /<app-model-combobox[\s\S]*?label="Review \(Revisión Independiente\)"[\s\S]*?\[\(modelValue\)\]="newProjectProfiles\.independent_review"/);
  assert.match(proyectosSrc, /<app-model-combobox[\s\S]*?label="Fallback \(Respaldo\)"[\s\S]*?\[\(modelValue\)\]="newProjectProfiles\.fallback"/);

  // Combobox integrated for thinking, execution, independent_review, fallback in Edit Modal
  assert.match(proyectosSrc, /<app-model-combobox[\s\S]*?label="Thinking \(Exploración\)"[\s\S]*?\[\(modelValue\)\]="editProjectProfiles\.thinking"/);
  assert.match(proyectosSrc, /<app-model-combobox[\s\S]*?label="Execution \(Código\)"[\s\S]*?\[\(modelValue\)\]="editProjectProfiles\.execution"/);
  assert.match(proyectosSrc, /<app-model-combobox[\s\S]*?label="Review \(Revisión Independiente\)"[\s\S]*?\[\(modelValue\)\]="editProjectProfiles\.independent_review"/);
  assert.match(proyectosSrc, /<app-model-combobox[\s\S]*?label="Fallback \(Respaldo\)"[\s\S]*?\[\(modelValue\)\]="editProjectProfiles\.fallback"/);
});

test('ModelComboboxComponent supports accessibility, instant search filtering and keyboard navigation', () => {
  // Accessibility contracts
  assert.match(comboboxSrc, /role="combobox"/);
  assert.match(comboboxSrc, /\[attr\.aria-expanded\]="isOpen"/);
  assert.match(comboboxSrc, /role="listbox"/);
  assert.match(comboboxSrc, /role="option"/);

  // Search input and real-time filtering
  assert.match(comboboxSrc, /placeholder="Buscar por proveedor o modelo…"/);
  assert.match(comboboxSrc, /get filteredModels\(\): ModelOption\[\]/);

  // Keyboard navigation
  assert.match(comboboxSrc, /case 'ArrowDown':/);
  assert.match(comboboxSrc, /case 'ArrowUp':/);
  assert.match(comboboxSrc, /case 'Enter':/);
  assert.match(comboboxSrc, /case 'Escape':/);
});

test('Model mapping separates OpenRouter upstream identity from DeepSeek direct without conflation', () => {
  // Format model entry separates OpenRouter from DeepSeek direct
  assert.match(proyectosSrc, /group:\s*'OpenRouter \(vía OpenCode\)'/);
  assert.match(proyectosSrc, /provider_id:\s*'openrouter'/);
  assert.match(proyectosSrc, /group:\s*'DeepSeek \(API directa\)'/);
  assert.match(proyectosSrc, /provider_id:\s*'deepseek'/);

  // Does not force DeepSeek prefix on all OpenRouter models
  assert.doesNotMatch(proyectosSrc, /label\s*=\s*`DeepSeek \$\{this\.friendlyDeepseekName\(modelKey\)\} — OpenRouter`/);

  // Preserves existing profiles when editing
  assert.match(proyectosSrc, /const existing = proj\?\.agent_profiles\?\.\[role\];/);
  assert.match(proyectosSrc, /if \(existing && existing\.model_id === modelId\) \{\s*return existing;\s*\}/);
});
