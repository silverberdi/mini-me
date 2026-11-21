import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const component = fs.readFileSync(
  path.join(root, 'src/app/features/trabajo-actual/trabajo-actual.component.ts'),
  'utf8',
);

test('Trabajo actual reads the current Run payload without stale fallbacks', () => {
  assert.match(component, /run\.stop_details\?\.\['human_payload'\]/);
  assert.doesNotMatch(component, /human_request/);
  assert.doesNotMatch(component, /metadata\?\.\['human_payload'\]/);
});

test('current gate question and options are rendered from the same payload', () => {
  assert.match(component, /humanGateQuestion\(\)/);
  assert.match(component, /humanGateOptions\(\)/);
  assert.match(component, /Opciones para responder a este gate/);
});

test('gate uses Spanish presentation while preserving exact source text and response values', () => {
  assert.match(component, /payload\?\.question_es \|\| 'La pregunta del workflow aún no tiene una presentación en español\.'/);
  assert.match(component, /humanGateOriginalQuestion\(\)/);
  assert.match(component, /humanGateOptionLabel\(opt, i\)/);
  assert.match(component, /humanGateOptionOriginalLabel\(opt, i\)/);
  assert.match(component, /payload\?\.options_es\?\.\[index\] \|\| option\?\.label_es/);
  assert.match(component, /const responseText = typeof option\?\.response_text === 'string' \? option\.response_text : ''/);
  assert.match(component, /this\.operatorResponse\.set\(responseText \|\| option\?\.label \|\| option\?\.id/);
  assert.match(component, /Texto original:/);
});

test('proposal-review gate renders structured findings and original reviewer evidence', () => {
  assert.match(component, /humanGateFindings\(\)/);
  assert.match(component, /finding\.severity/);
  assert.match(component, /humanGateSeverityLabel\(finding\.severity\)/);
  assert.match(component, /La revisión marcó un hallazgo/);
  assert.match(component, /Requisito en riesgo/);
  assert.match(component, /la propuesta seguirá sin cumplirlo/);
  assert.match(component, /Corrección que pide el reviewer/);
  assert.match(component, /finding\.location/);
  assert.match(component, /finding\.violated_requirement/);
  assert.match(component, /finding\.expected_correction/);
  assert.match(component, /humanGateReviewerSummary\(\)/);
  assert.match(component, /Resumen original del reviewer/);
  assert.match(component, /Requisito en riesgo/);
  assert.match(component, /Corrección que pide el reviewer/);
});

test('proposal-review options identify system suggestions and retain free-text response', () => {
  assert.match(component, /humanGateOptionsSource\(\)/);
  assert.match(component, /Sugerencia del sistema; puedes responder con otro texto/);
  assert.match(component, /Opciones originales del workflow/);
  assert.match(component, /name="operatorResponse"/);
  assert.match(component, /submitHumanResponse\(\$event\)/);
  assert.match(component, /Respuesta explícita del operador/);
});

test('optional gate evidence fields render only when present and preserve old payload compatibility', () => {
  assert.match(component, /humanGateAffectedItems\(\): any\[\] \{[\s\S]*?Array\.isArray\(payload\?\.affected_items\) \? payload\.affected_items : \[\]/);
  assert.match(component, /humanGateDiff\(\): string \{[\s\S]*?if \(!diff \|\| typeof diff !== 'object'\) return ''[\s\S]*?diff\.status === 'NOT_APPLICABLE'[\s\S]*?diff\.status === 'UNAVAILABLE'/);
  assert.match(component, /humanGateOptionExplanation\(option: any, index: number\): string/);
  assert.match(component, /humanGateDescription\(\): string/);
  assert.match(component, /\*ngIf="humanGateAffectedItems\(\)\.length > 0"/);
  assert.match(component, /\*ngIf="humanGateDiff\(\)"/);
  assert.match(component, /\*ngIf="humanGateOptionExplanation\(opt, i\)"/);
  assert.match(component, /const value = Array\.isArray\(explanations\)/);
});

test('selecting a generated correction places its complete response text in the clarification', () => {
  assert.match(component, /selectHumanGateOption\(opt\)/);
  assert.match(component, /option\?\.response_text/);
  assert.match(component, /this\.operatorResponse\.set\(responseText \|\| option\?\.label \|\| option\?\.id/);
  assert.match(component, /opt\.source === 'system_generated'/);
  assert.match(component, /opt\.description/);
});

test('Trabajo actual fallback never selects an inactive historical run', () => {
  const targetRun = component.match(/readonly targetRun = computed\(\(\) => \{([\s\S]*?)\n  \}\);/);
  assert.ok(targetRun, 'targetRun computed selector should exist');
  assert.match(targetRun[1], /const queryRunId = this\.route\.snapshot\.queryParamMap\.get\('run'\)/);
  assert.match(targetRun[1], /if \(found\) return found/);

  const fallback = targetRun[1].match(/return (runs\.find\(r => r\.is_active\) \|\| null);/);
  assert.ok(fallback, 'fallback should select an active run or none');
  const selectFallback = new Function('runs', `return ${fallback[1]};`);
  assert.equal(selectFallback([{ is_active: false, status: 'HUMAN_REQUIRED' }]), null);
  assert.equal(selectFallback([{ is_active: true, status: 'HUMAN_REQUIRED' }]).is_active, true);
});

test('operator response submits through the existing authorized request endpoint', () => {
  assert.match(component, /\/api\/v1\/projects\/\$\{encodeURIComponent\(run\.project_id\)\}\/requests\/run/);
  assert.match(component, /operator_clarification: answer/);
  assert.match(component, /idempotency_key: idempotencyKey/);
  assert.match(component, /humanResponseIdempotencyKey\(run, answer\)/);
  assert.match(component, /await this\.refresh\.refreshRuns\(\)/);
});

test('Trabajo actual renders Spanish explanation and Apply diagnostic context', () => {
  assert.match(component, /humanGateExplanationEs\(\)/);
  assert.match(component, /Contexto Explicativo \(Español\):/);
  assert.match(component, /humanGateAttempts\(\)/);
  assert.match(component, /Diagnóstico de Implementación \(Apply\):/);
  assert.match(component, /humanGatePendingTasks\(\)/);
  assert.match(component, /humanGateCandidateSha\(\)/);
  assert.match(component, /humanGateLogsAvailable\(\)/);
});

test('Trabajo actual suppresses "Sin anomalías reportadas" when human attention is required', () => {
  assert.match(component, /!targetRun\(\)\?\.error_detail && !isHumanRequired\(\)/);
  assert.match(component, /Intervención humana requerida/);
});

