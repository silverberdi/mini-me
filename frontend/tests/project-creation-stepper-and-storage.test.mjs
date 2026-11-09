import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const sourceRoot = new URL('../src/app/', import.meta.url);
const refreshSrc = fs.readFileSync(new URL('core/refresh.service.ts', sourceRoot), 'utf8');
const proyectosSrc = fs.readFileSync(new URL('features/proyectos/proyectos.component.ts', sourceRoot), 'utf8');

test('RefreshService persists selectedProjectId in localStorage under minime_selected_project_id', () => {
  // Constant defined and used
  assert.match(refreshSrc, /const SELECTED_PROJECT_STORAGE_KEY = 'minime_selected_project_id';/);

  // Initial value reads from localStorage
  assert.match(refreshSrc, /RefreshService\.getStoredProjectId\(\)/);
  assert.match(refreshSrc, /localStorage\.getItem\(SELECTED_PROJECT_STORAGE_KEY\)/);

  // setSelectedProject writes to localStorage
  assert.match(refreshSrc, /localStorage\.setItem\(SELECTED_PROJECT_STORAGE_KEY,\s*projectId\)/);
});

test('ProyectosComponent renders a 4-stage creation stepper in the creation modal', () => {
  // 4 stages definition
  assert.match(proyectosSrc, /createStages\s*=\s*\[/);
  assert.match(proyectosSrc, /1\.\s*Conexión GitHub & Grants/);
  assert.match(proyectosSrc, /2\.\s*Repositorio Gestionado/);
  assert.match(proyectosSrc, /3\.\s*Aprovisionamiento de Skills/);
  assert.match(proyectosSrc, /4\.\s*Verificación de Preparación/);

  // Stepper rendering in create modal template
  assert.match(proyectosSrc, /Progreso de Creación Guiada/);
  assert.match(proyectosSrc, /creationStep\(\)\s*>\s*i\s*\+\s*1\s*\?\s*'✓'/);

  // creationStep signal is initialized and updated
  assert.match(proyectosSrc, /creationStep\s*=\s*signal<number>\(0\);/);
  assert.match(proyectosSrc, /this\.creationStep\.set\(1\);/);
});

test('ProyectosComponent displays clear guidance for GitHub App permission errors', () => {
  // Helper to detect grant errors
  assert.match(proyectosSrc, /isGitHubGrantError\(msg:\s*string\s*\|\s*null\):\s*boolean/);

  // Guidance banner in modal
  assert.match(proyectosSrc, /Autorización de GitHub requerida/);
  assert.match(proyectosSrc, /Installed GitHub Apps/);
  assert.match(proyectosSrc, /All repositories/);
});
