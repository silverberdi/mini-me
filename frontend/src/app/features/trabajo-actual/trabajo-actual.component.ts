import { Component, computed, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, ActivatedRoute } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { RefreshService } from '../../core/refresh.service';
import { ApiService } from '../../core/api.service';

interface PipelineStage {
  key: string;
  label: string;
}

@Component({
  selector: 'app-trabajo-actual',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule],
  template: `
    <div class="space-y-6">
      <!-- Header -->
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-slate-800/40 p-6 rounded-2xl border border-slate-700/50 backdrop-blur-sm">
        <div>
          <h1 class="text-2xl font-bold tracking-tight text-white flex items-center gap-3">
            <span>Trabajo Actual</span>
            <span *ngIf="targetRun()" class="text-xs font-mono font-bold px-2.5 py-1 rounded-md bg-sky-500/10 text-sky-400 border border-sky-500/20">
              {{ targetRun()?.run_id }}
            </span>
          </h1>
          <p class="text-sm text-slate-400 mt-1">Supervisión detallada de la ejecución, avance de fases y resolución de atención humana.</p>
        </div>
        <div class="flex items-center gap-2">
          <a routerLink="/trabajo" class="px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-slate-300 transition-colors flex items-center gap-1.5">
            <span>&larr;</span>
            <span>Volver a Trabajo</span>
          </a>
        </div>
      </div>

      <!-- No Run Available State -->
      <div *ngIf="!targetRun()" class="bg-slate-800/30 rounded-2xl border border-slate-700/40 p-12 text-center">
        <div class="w-12 h-12 rounded-full bg-slate-800 flex items-center justify-center mx-auto mb-4 text-slate-500 text-xl">
          ⚙️
        </div>
        <h3 class="text-base font-semibold text-slate-300">No hay un Run disponible para supervisión</h3>
        <p class="text-sm text-slate-500 mt-1 max-w-sm mx-auto">
          El Run solicitado no fue expuesto o no existe una ejecución activa en el proyecto seleccionado.
        </p>
      </div>

      <!-- Run Content -->
      <div *ngIf="targetRun()" class="space-y-6">
        <!-- Main Run Header -->
        <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 p-6 backdrop-blur-sm">
          <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <div class="flex items-center gap-3 flex-wrap">
                <span class="font-mono text-sm font-bold text-white">{{ targetRun()?.run_id }}</span>
                <span class="px-2.5 py-1 text-xs font-semibold rounded-lg"
                      [ngClass]="{
                        'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20': targetRun()?.status === 'SUCCEEDED' || targetRun()?.status === 'COMPLETED',
                        'bg-sky-500/10 text-sky-400 border border-sky-500/20': targetRun()?.status === 'RUNNING' || targetRun()?.status === 'IN_PROGRESS',
                        'bg-rose-500/10 text-rose-400 border border-rose-500/20': targetRun()?.status === 'FAILED' || targetRun()?.status === 'ERRORED',
                        'bg-amber-500/10 text-amber-400 border border-amber-500/20': targetRun()?.status === 'PAUSED' || targetRun()?.status === 'WAITING' || isHumanRequired()
                      }">
                  {{ targetRun()?.status }}
                </span>
                <span *ngIf="targetRun()?.is_active" class="px-2 py-0.5 text-[11px] font-semibold rounded-full bg-sky-500/20 text-sky-300 border border-sky-500/30">
                  Activo
                </span>
              </div>
              <h2 class="text-lg font-bold text-white mt-2">{{ targetRun()?.change_name || 'Sin cambio OpenSpec asignado' }}</h2>
              <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-400 font-mono mt-1">
                <span>Proyecto: <strong class="text-slate-300">{{ targetRun()?.project_id }}</strong></span>
                <span>Request: <strong class="text-slate-300">{{ targetRun()?.request_id || 'N/A' }}</strong></span>
                <span>Inicio: <strong class="text-slate-300">{{ targetRun()?.created_at || 'N/A' }}</strong></span>
              </div>
            </div>
            <div class="flex flex-col items-start md:items-end gap-1">
              <span class="text-xs text-slate-400 uppercase font-mono">Etapa Actual</span>
              <span class="px-3 py-1.5 rounded-xl bg-slate-900 border border-slate-700 text-sm font-bold text-sky-400 font-mono">
                {{ targetRun()?.stage }}
              </span>
            </div>
          </div>
        </div>

        <!-- 10-Stage Pipeline Stepper -->
        <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 p-6 backdrop-blur-sm space-y-4">
          <div class="flex items-center justify-between">
            <h2 class="text-sm font-bold text-white uppercase tracking-wider font-mono">Fases del Pipeline de Orquestación</h2>
            <span class="text-xs text-slate-500 font-mono">10 Etapas Verificables</span>
          </div>

          <div class="grid grid-cols-2 sm:grid-cols-5 lg:grid-cols-10 gap-2">
            <div *ngFor="let stage of pipelineStages; let idx = index"
                 class="p-2.5 rounded-xl border flex flex-col items-center text-center transition-all"
                 [ngClass]="getStageClass(stage.key, idx)">
              <span class="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold font-mono mb-1.5"
                    [ngClass]="getBadgeClass(stage.key, idx)">
                {{ idx + 1 }}
              </span>
              <span class="text-[11px] font-semibold leading-tight line-clamp-2">
                {{ stage.label }}
              </span>
            </div>
          </div>

          <div class="text-xs text-slate-400 font-mono pt-2 border-t border-slate-800 flex items-center justify-between">
            <span>Etapa actual observada: <strong class="text-sky-400">{{ targetRun()?.stage || 'UNKNOWN' }}</strong></span>
            <span>Salidas y evidencias vinculadas a SHA duradero</span>
          </div>
        </div>

        <!-- HUMAN_REQUIRED Interactive Attention Gate -->
        <div *ngIf="isHumanRequired()" class="p-6 rounded-2xl bg-amber-500/10 border-2 border-amber-500/40 space-y-4 shadow-xl">
          <div class="flex items-start gap-3">
            <div class="w-10 h-10 rounded-xl bg-amber-500/20 text-amber-300 flex items-center justify-center text-2xl shrink-0">
              ⚠️
            </div>
            <div>
              <h3 class="text-base font-bold text-white">Atención Humana Requerida (HUMAN_REQUIRED)</h3>
              <p class="text-xs text-slate-300 mt-1">
                El workflow se encuentra detenido a la espera de una aclaración o decisión explícita del operador para continuar.
              </p>
            </div>
          </div>

          <!-- Question Prompt -->
          <div class="p-4 rounded-xl bg-slate-900/90 border border-amber-500/30 space-y-2">
            <span class="text-xs font-semibold uppercase tracking-wider text-amber-400 font-mono">Pregunta del Workflow:</span>
            <p class="text-sm text-slate-100 font-medium whitespace-pre-wrap">{{ humanGateQuestion() }}</p>
          </div>

          <!-- Options (if available) -->
          <div *ngIf="humanGateOptions().length > 0" class="space-y-2">
            <span class="text-xs font-semibold text-slate-300 font-mono">Opciones sugeridas por el agente:</span>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <button *ngFor="let opt of humanGateOptions()"
                      type="button"
                      (click)="operatorResponse.set(opt.label || opt.id || opt)"
                      class="p-3 text-left rounded-xl bg-slate-900/60 hover:bg-slate-800 border border-slate-700 hover:border-sky-500 transition-colors cursor-pointer group">
                <div class="text-xs font-bold text-white group-hover:text-sky-300">{{ opt.label || opt.id || opt }}</div>
                <div *ngIf="opt.description" class="text-[11px] text-slate-400 mt-0.5">{{ opt.description }}</div>
              </button>
            </div>
          </div>

          <!-- Response Form -->
          <form (submit)="submitHumanResponse($event)" class="space-y-3 pt-2">
            <div>
              <label for="clarificationInput" class="block text-xs font-medium text-slate-300 mb-1">
                Respuesta explícita del operador:
              </label>
              <textarea
                id="clarificationInput"
                rows="4"
                [ngModel]="operatorResponse()"
                (ngModelChange)="operatorResponse.set($event)"
                name="operatorResponse"
                placeholder="Escribe la respuesta, aclaración u opción seleccionada para continuar la ejecución..."
                required
                class="w-full bg-slate-950 border border-slate-700 rounded-xl p-3 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500">
              </textarea>
            </div>

            <div class="flex items-center justify-between">
              <span class="text-xs text-slate-400 font-mono">La respuesta se envía a la autoridad duradera del backend.</span>
              <button
                type="submit"
                [disabled]="isSubmitting() || !operatorResponse().trim()"
                class="px-5 py-2.5 rounded-xl bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white font-semibold text-xs tracking-wide shadow-lg transition-all flex items-center gap-2 cursor-pointer">
                <span *ngIf="isSubmitting()" class="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
                <span>{{ isSubmitting() ? 'Enviando…' : 'Enviar respuesta y continuar' }}</span>
              </button>
            </div>

            <div *ngIf="submissionMessage()"
                 class="p-3 rounded-xl text-xs font-mono"
                 [ngClass]="submissionSuccess() ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'">
              {{ submissionMessage() }}
            </div>
          </form>
        </div>

        <!-- Normal State Gate Banner (when not human required) -->
        <div *ngIf="!isHumanRequired()" class="p-4 rounded-xl bg-slate-800/40 border border-slate-700/50 flex items-center justify-between text-xs text-slate-400">
          <span class="flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-emerald-400"></span>
            <span>No existe bloqueo de atención humana activo. El workflow avanza de forma autónoma.</span>
          </span>
          <span class="font-mono text-slate-500">WAITING_CAPACITY / UNKNOWN no generan preguntas.</span>
        </div>

        <!-- Technical Identity & Evidence Grid -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 p-6 backdrop-blur-sm space-y-4">
            <h3 class="text-base font-semibold text-white">Identidad & Control de Versiones</h3>
            <div class="space-y-3 text-xs font-mono">
              <div class="flex justify-between py-2 border-b border-slate-700/40">
                <span class="text-slate-400 font-sans">Run ID:</span>
                <span class="text-slate-200 font-bold">{{ targetRun()?.run_id }}</span>
              </div>
              <div class="flex justify-between py-2 border-b border-slate-700/40">
                <span class="text-slate-400 font-sans">Base SHA:</span>
                <span class="text-slate-300 truncate max-w-[200px]">{{ targetRun()?.base_sha || 'No disponible' }}</span>
              </div>
              <div class="flex justify-between py-2 border-b border-slate-700/40">
                <span class="text-slate-400 font-sans">Candidate SHA:</span>
                <span class="text-slate-300 truncate max-w-[200px]">{{ targetRun()?.candidate_sha || targetRun()?.current_candidate_sha || 'Pendiente de generación' }}</span>
              </div>
              <div class="flex justify-between py-2 border-b border-slate-700/40">
                <span class="text-slate-400 font-sans">Agente Ejecutor:</span>
                <span class="text-slate-200">{{ targetRun()?.active_agent_id || 'Autónomo / Ninguno' }}</span>
              </div>
            </div>
          </div>

          <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 p-6 backdrop-blur-sm space-y-4">
            <h3 class="text-base font-semibold text-white">Diagnóstico & Supervisión</h3>
            <div *ngIf="targetRun()?.error_detail" class="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs font-mono whitespace-pre-wrap">
              {{ targetRun()?.error_detail }}
            </div>
            <div *ngIf="!targetRun()?.error_detail" class="p-4 rounded-xl bg-slate-900/60 border border-slate-700/40 text-slate-400 text-xs space-y-1.5">
              <div class="text-emerald-400 font-semibold">✓ Sin anomalías reportadas</div>
              <p>El orquestador no ha emitido errores fatales de ejecución para este run.</p>
            </div>
            <div class="text-xs text-slate-500 font-mono">
              Última actualización: {{ targetRun()?.updated_at || 'Reciente' }}
            </div>
          </div>
        </div>
      </div>
    </div>
  `
})
export class TrabajoActualComponent {
  private route = inject(ActivatedRoute);
  private api = inject(ApiService);
  public refresh = inject(RefreshService);

  readonly operatorResponse = signal<string>('');
  readonly isSubmitting = signal<boolean>(false);
  readonly submissionMessage = signal<string | null>(null);
  readonly submissionSuccess = signal<boolean>(false);

  readonly pipelineStages: PipelineStage[] = [
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
  ];

  readonly targetRun = computed(() => {
    const runs = this.refresh.runs();
    const queryRunId = this.route.snapshot.queryParamMap.get('run');
    if (queryRunId) {
      const found = runs.find(r => r.run_id === queryRunId);
      if (found) return found;
    }
    // Default to active run or first available
    return runs.find(r => r.is_active) || runs.find(r => r.status === 'RUNNING' || r.status === 'IN_PROGRESS' || r.status === 'HUMAN_REQUIRED') || runs[0] || null;
  });

  isHumanRequired(): boolean {
    const run = this.targetRun();
    if (!run) return false;
    const gate = (run as any).human_gate || run.status;
    const details = (run as any).stop_details?.human_payload || (run as any).stop_details?.human_request || run.metadata?.['human_payload'];
    return gate === 'HUMAN_REQUIRED' || !!details;
  }

  humanGateQuestion(): string {
    const run = this.targetRun();
    if (!run) return '';
    const payload = (run as any).stop_details?.human_payload || (run as any).stop_details?.human_request || run.metadata?.['human_payload'];
    return payload?.question || payload?.prompt || 'El workflow requiere aclaración u autorización del operador para continuar.';
  }

  humanGateOptions(): any[] {
    const run = this.targetRun();
    if (!run) return [];
    const payload = (run as any).stop_details?.human_payload || (run as any).stop_details?.human_request || run.metadata?.['human_payload'];
    return Array.isArray(payload?.options) ? payload.options : [];
  }

  getStageClass(stageKey: string, idx: number): string {
    const current = this.targetRun()?.stage;
    const currentIdx = this.pipelineStages.findIndex(s => s.key === current);

    if (stageKey === current) {
      return 'border-sky-500 bg-sky-500/10 text-sky-300 shadow-md shadow-sky-500/10';
    } else if (currentIdx !== -1 && idx < currentIdx) {
      return 'border-emerald-500/30 bg-emerald-500/5 text-emerald-400';
    } else {
      return 'border-slate-800 bg-slate-900/40 text-slate-500';
    }
  }

  getBadgeClass(stageKey: string, idx: number): string {
    const current = this.targetRun()?.stage;
    const currentIdx = this.pipelineStages.findIndex(s => s.key === current);

    if (stageKey === current) {
      return 'bg-sky-500 text-white animate-pulse';
    } else if (currentIdx !== -1 && idx < currentIdx) {
      return 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40';
    } else {
      return 'bg-slate-800 text-slate-500';
    }
  }

  async submitHumanResponse(event: Event): Promise<void> {
    event.preventDefault();
    const run = this.targetRun();
    const answer = this.operatorResponse().trim();
    if (!run || !answer) return;

    this.isSubmitting.set(true);
    this.submissionMessage.set(null);

    try {
      const response = await this.api.post(
        `/api/v1/projects/${encodeURIComponent(run.project_id)}/requests/run`,
        { operator_clarification: answer }
      );

      if (response.ok) {
        this.submissionSuccess.set(true);
        this.submissionMessage.set('Respuesta aceptada por el backend. Actualizando estado de la autoridad…');
        this.operatorResponse.set('');
        await this.refresh.read();
      } else {
        this.submissionSuccess.set(false);
        this.submissionMessage.set(`Error al confirmar respuesta: ${response.error || 'Error no especificado'}`);
      }
    } catch (e: any) {
      this.submissionSuccess.set(false);
      this.submissionMessage.set(`Error de comunicación: ${e.message || e}`);
    } finally {
      this.isSubmitting.set(false);
    }
  }
}
