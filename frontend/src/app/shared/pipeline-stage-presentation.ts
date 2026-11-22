export interface PipelineStage {
  readonly key: string;
  readonly label: string;
}

export const PIPELINE_STAGES: readonly PipelineStage[] = Object.freeze([
  { key: 'ADMITTED', label: 'Admisión' },
  { key: 'EXPLORING', label: 'Exploración' },
  { key: 'PROPOSING', label: 'Propuesta' },
  { key: 'PROPOSAL_REVIEW', label: 'Review Propuesta' },
  { key: 'IMPLEMENTING', label: 'Implementación' },
  { key: 'RUNNING_TESTS', label: 'Tests' },
  { key: 'VERIFYING', label: 'Verificación' },
  { key: 'CODE_REVIEW', label: 'Review Código' },
  { key: 'PREPARING_PR', label: 'Preparar PR' },
  { key: 'COMPLETED', label: 'Cierre' },
]);

export const STAGE_ILLUSTRATION_PATHS: Readonly<Record<string, string>> = Object.freeze({
  ADMITTED: '/illustrations/admitted.png',
  EXPLORING: '/illustrations/exploring.png',
  PROPOSING: '/illustrations/proposing.png',
  PROPOSAL_REVIEW: '/illustrations/proposal-review.png',
  IMPLEMENTING: '/illustrations/implementing.png',
  RUNNING_TESTS: '/illustrations/running-tests.png',
  VERIFYING: '/illustrations/verifying.png',
  CODE_REVIEW: '/illustrations/code-review.png',
  PREPARING_PR: '/illustrations/preparing-pr.png',
  COMPLETED: '/illustrations/completed.png',
});

export function getStageIllustrationPath(stage: string | null | undefined): string | null {
  return stage ? STAGE_ILLUSTRATION_PATHS[stage] ?? null : null;
}

export function getStagePanelClass(stageKey: string, currentStage: string | null | undefined): string {
  const currentIndex = PIPELINE_STAGES.findIndex(stage => stage.key === currentStage);
  const stageIndex = PIPELINE_STAGES.findIndex(stage => stage.key === stageKey);

  if (stageKey === currentStage) {
    return 'border-sky-500 bg-sky-500/10 text-sky-300 shadow-md shadow-sky-500/10';
  }
  if (currentIndex !== -1 && stageIndex !== -1 && stageIndex < currentIndex) {
    return 'border-emerald-500/30 bg-emerald-500/5 text-emerald-400';
  }
  return 'border-slate-800 bg-slate-900/40 text-slate-500';
}

export function getStageBadgeClass(stageKey: string, currentStage: string | null | undefined): string {
  const currentIndex = PIPELINE_STAGES.findIndex(stage => stage.key === currentStage);
  const stageIndex = PIPELINE_STAGES.findIndex(stage => stage.key === stageKey);

  if (stageKey === currentStage) {
    return 'bg-sky-500 text-white animate-pulse';
  }
  if (currentIndex !== -1 && stageIndex !== -1 && stageIndex < currentIndex) {
    return 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40';
  }
  return 'bg-slate-800 text-slate-500';
}
