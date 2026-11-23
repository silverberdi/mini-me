import { Component, computed, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { RefreshService } from '../../core/refresh.service';
import { AnalogGaugeComponent } from '../../shared/analog-gauge.component';
import {
  getStageBadgeClass,
  getStageIllustrationPath,
  getStagePanelClass,
  PIPELINE_STAGES,
} from '../../shared/pipeline-stage-presentation';
import { toDashboardCostChartPoints } from './dashboard-cost-chart';
import type { OrchestrationRun, QuotaObservation } from '../../core/models';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, RouterModule, AnalogGaugeComponent],
  template: `
    <div class="space-y-6">

      <!-- Human Attention Required Alert Banner -->
      <div *ngIf="refresh.humanRequiredRun()" class="p-5 rounded-2xl bg-rose-500/10 border border-rose-500/30 flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-lg shadow-rose-500/5 animate-pulse">
        <div class="flex items-start gap-3.5">
          <div class="w-10 h-10 rounded-xl bg-rose-500/20 text-rose-300 flex items-center justify-center text-xl shrink-0">
            ⚠️
          </div>
          <div>
            <h3 class="text-base font-bold text-white">Atención Humana Requerida (HUMAN_REQUIRED)</h3>
            <p class="text-xs text-slate-300 mt-0.5">
              El orquestador autónomo se encuentra detenido esperando una decisión, aclaración o confirmación del operador en el Run
              <span class="font-mono font-bold text-sky-300">{{ refresh.humanRequiredRun()?.run_id }}</span>.
            </p>
          </div>
        </div>
        <a routerLink="/trabajo-actual" class="px-4 py-2 rounded-xl bg-rose-600 hover:bg-rose-500 text-white font-semibold text-xs tracking-wide shadow-md transition-all self-end md:self-center shrink-0 flex items-center gap-1.5">
          <span>Responder en Trabajo Actual</span>
          <span>&rarr;</span>
        </a>
      </div>

      <!-- Telemetry Capacity Gauges (4 Providers) -->
      <div class="space-y-3">
        <div class="flex items-center justify-between px-1">
          <h2 class="text-sm font-bold text-white uppercase tracking-wider font-mono">Cuota Disponible por Agente / Proveedor</h2>
          <span class="text-xs text-slate-500 font-mono">Telemetría de Capacidad en Tiempo Real</span>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <app-analog-gauge
            label="Codex"
            unit="%"
            color="emerald"
            [value]="codexValue"
            [max]="100"
            [sublabel]="codexSublabel">
          </app-analog-gauge>

          <app-analog-gauge
            label="Antigravity"
            unit="%"
            color="sky"
            [value]="antigravityValue"
            [max]="100"
            [sublabel]="antigravitySublabel">
          </app-analog-gauge>

          <app-analog-gauge
            label="DeepSeek"
            unit="%"
            color="amber"
            [value]="deepseekValue"
            [max]="100"
            [textValue]="deepseekTextValue"
            [sublabel]="deepseekSublabel">
          </app-analog-gauge>

          <app-analog-gauge
            label="OpenRouter"
            unit="%"
            color="sky"
            [value]="openrouterValue"
            [max]="100"
            [sublabel]="openrouterSublabel">
          </app-analog-gauge>
        </div>
      </div>

      <!-- Line Chart Section (3 Independent Dimensions: Autonomy, Delivery Time, Settled Cost) -->
      <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 p-6 backdrop-blur-sm space-y-4 shadow-xl">
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-700/60 pb-4">
          <div>
            <h2 class="text-base font-bold text-white flex items-center gap-2">
              <span>Gráfica de Líneas de Efectividad</span>
              <span class="text-xs font-mono font-normal text-slate-400">(Tres Dimensiones Independientes)</span>
            </h2>
            <p class="text-xs text-slate-400 mt-0.5">Observabilidad de calidad/autonomía, duración efectiva y costo liquidado por ejecución terminada.</p>
          </div>
          <div class="flex items-center gap-1.5 bg-slate-900/80 p-1 rounded-xl border border-slate-800 self-start sm:self-auto">
            <button
              (click)="selectedDimension.set('autonomy')"
              [ngClass]="selectedDimension() === 'autonomy' ? 'bg-emerald-500 text-white shadow' : 'text-slate-400 hover:text-slate-200'"
              class="px-3 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer">
              1. Calidad / Autonomía
            </button>
            <button
              (click)="selectedDimension.set('time')"
              [ngClass]="selectedDimension() === 'time' ? 'bg-sky-500 text-white shadow' : 'text-slate-400 hover:text-slate-200'"
              class="px-3 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer">
              2. Tiempos de Entrega
            </button>
            <button
              (click)="selectedDimension.set('cost')"
              [ngClass]="selectedDimension() === 'cost' ? 'bg-amber-500 text-white shadow' : 'text-slate-400 hover:text-slate-200'"
              class="px-3 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer">
              3. Costo liquidado (USD)
            </button>
          </div>
        </div>

        <div class="p-4 rounded-xl bg-slate-950/70 border border-slate-800 space-y-3">
          <div class="flex items-center justify-between text-xs font-mono">
            <span class="text-slate-300 font-semibold flex items-center gap-2">
              <span class="w-2.5 h-2.5 rounded-full" [style.background-color]="chartColor"></span>
              {{ currentDimensionTitle }}
            </span>
            <span class="text-slate-400 font-mono">Unidad: {{ currentDimensionUnit }}</span>
          </div>

          <div class="relative w-full h-52">
            <div *ngIf="dataPoints.length === 0" class="h-full flex flex-col items-center justify-center text-center p-6 text-slate-500 space-y-1" role="status" aria-live="polite">
              <span class="text-sm font-medium text-slate-400">{{ selectedDimension() === 'cost' ? 'Sin datos de costo liquidado' : 'Sin ejecuciones históricas registradas' }}</span>
              <span class="text-xs font-mono">{{ selectedDimension() === 'cost' ? 'No existe un importe verificable en el ledger.' : 'Las métricas de efectividad se trazarán automáticamente al completarse ciclos reales.' }}</span>
            </div>

            <svg *ngIf="dataPoints.length > 0" viewBox="0 0 600 170" preserveAspectRatio="none" class="w-full h-full overflow-visible">
              <!-- Grid lines -->
              <line x1="45" y1="20" x2="580" y2="20" stroke="#334155" stroke-dasharray="3 3" stroke-width="0.75" />
              <line x1="45" y1="65" x2="580" y2="65" stroke="#334155" stroke-dasharray="3 3" stroke-width="0.75" />
              <line x1="45" y1="110" x2="580" y2="110" stroke="#334155" stroke-dasharray="3 3" stroke-width="0.75" />
              <line x1="45" y1="145" x2="580" y2="145" stroke="#475569" stroke-width="1" />

              <!-- Y Axis Labels -->
              <text x="38" y="24" text-anchor="end" fill="#64748b" font-size="10" font-family="monospace">{{ yMaxLabel }}</text>
              <text x="38" y="70" text-anchor="end" fill="#64748b" font-size="10" font-family="monospace">{{ yMidLabel }}</text>
              <text x="38" y="148" text-anchor="end" fill="#64748b" font-size="10" font-family="monospace">{{ yMinLabel }}</text>

              <!-- Line Chart Polyline -->
              <polyline
                fill="none"
                stroke-width="2.5"
                stroke-linecap="round"
                stroke-linejoin="round"
                [attr.points]="chartPoints"
                [attr.stroke]="chartColor"
              />

              <!-- Data Point Circles and Labels -->
              <g *ngFor="let pt of dataPoints">
                <circle [attr.cx]="pt.x" [attr.cy]="pt.y" r="5.5" [attr.fill]="chartColor" stroke="#020617" stroke-width="2" />
                <text [attr.x]="pt.x" [attr.y]="pt.y - 10" text-anchor="middle" fill="#f8fafc" font-size="11" font-weight="bold" font-family="monospace">
                  {{ pt.displayVal }}
                </text>
                <text [attr.x]="pt.x" y="162" text-anchor="middle" fill="#94a3b8" font-size="10" font-family="monospace">
                  {{ pt.label }}
                </text>
              </g>
            </svg>
          </div>

          <div *ngIf="selectedDimension() === 'cost' && refresh.cost().status === 'available'" class="grid grid-cols-1 md:grid-cols-2 gap-3" aria-label="Costos liquidados por proveedor">
            <div *ngFor="let provider of refresh.cost().providers" class="rounded-xl border border-slate-700/50 bg-slate-900/60 p-4">
              <div class="flex items-center justify-between">
                <span class="text-sm font-semibold text-slate-200">{{ provider.label }}</span>
                <span class="font-mono text-sm text-amber-300">&#36;{{ provider.amount_usd }} USD</span>
              </div>
              <div *ngFor="let model of provider.models" class="mt-2 flex justify-between text-xs text-slate-400">
                <span>{{ model.model }}</span><span class="font-mono">&#36;{{ model.amount_usd }}</span>
              </div>
            </div>
          </div>

          <div class="flex items-center justify-between text-[11px] text-slate-500 pt-2 border-t border-slate-900 font-mono">
            <span>{{ selectedDimension() === 'cost' ? (refresh.cost().status === 'available' ? dataPoints.length + ' puntos de costo liquidados' : 'Costo liquidado no disponible') : dataPoints.length + ' ejecuciones históricas trazadas' }}</span>
            <span>Métricas duraderas calculadas sin simulación ni interpolación</span>
          </div>
        </div>
      </div>

      <!-- Active Change Summary -->
      <section class="bg-slate-800/40 rounded-2xl border border-slate-700/50 p-4 sm:p-5 backdrop-blur-sm space-y-4" aria-labelledby="active-change-heading" data-testid="active-change-card">
        <div class="flex items-center justify-between gap-3">
          <h2 id="active-change-heading" class="text-base font-semibold text-white">Change activo</h2>
          <span *ngIf="refresh.activeProject().project_id" class="text-xs font-mono text-slate-400 truncate">{{ refresh.activeProject().project_id }}</span>
        </div>

        <ng-container *ngIf="activeRun() as run; else noActiveRun">
          <div class="flex items-start gap-3 sm:gap-5 min-w-0">
            <div class="flex-1 min-w-0 space-y-2">
              <h3 class="text-sm sm:text-base font-bold text-white break-words" data-testid="active-change-name">
                {{ run.change_name || 'Change sin nombre asignado' }}
              </h3>
              <div *ngIf="activeRequest() as request" class="text-xs sm:text-sm text-slate-300 break-words" data-testid="active-change-request">
                <span *ngIf="request.issue_number || request.number" class="font-mono font-bold text-sky-400 mr-1">
                  #{{ request.issue_number || request.number }}
                </span>
                <span>{{ request.title }}</span>
              </div>
              <div class="flex flex-wrap items-center gap-2">
                <span class="px-2.5 py-1 text-xs font-semibold rounded-lg border"
                      [ngClass]="getStageBadgeClass(run.stage, run.stage)"
                      [title]="run.stage"
                      data-testid="active-change-stage">
                  Etapa: {{ stageLabel(run.stage) }}
                </span>
                <span class="px-2.5 py-1 text-xs font-semibold rounded-lg border"
                      [ngClass]="runStatusClass(run.status)"
                      data-testid="active-change-status">
                  {{ run.status }}
                </span>
              </div>
            </div>
            <div *ngIf="stageIllustrationPath(run.stage) as illustrationPath" class="h-20 w-24 sm:h-24 sm:w-32 shrink-0 flex items-center justify-center" data-testid="active-change-illustration-slot">
              <img [src]="illustrationPath" [alt]="'Ilustración de la etapa ' + stageLabel(run.stage)" class="max-h-full max-w-full object-contain" data-testid="active-change-illustration" />
            </div>
          </div>

          <div *ngIf="activeStageIndex(run) !== -1" class="grid grid-cols-10 gap-1 sm:gap-1.5" role="list" aria-label="Avance por etapas" data-testid="active-change-stage-progress">
            <span *ngFor="let stage of pipelineStages; let idx = index"
                  class="h-5 min-w-0 sm:h-6 rounded-md border flex items-center justify-center text-[10px] sm:text-xs font-bold font-mono transition-colors"
                  [ngClass]="getStageBadgeClass(stage.key, run.stage)"
                  [attr.aria-current]="stage.key === run.stage ? 'step' : null"
                  [attr.aria-label]="stage.label + (stage.key === run.stage ? ', etapa actual' : idx < activeStageIndex(run) ? ', completada' : ', pendiente')"
                  [title]="stage.label"
                  role="listitem">
              {{ idx + 1 }}
            </span>
          </div>

          <div class="flex justify-end pt-1">
            <a routerLink="/trabajo-actual" [queryParams]="{ run: run.run_id, project: run.project_id }"
               class="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-xl bg-sky-600 px-4 py-2 text-xs font-semibold text-white transition-colors hover:bg-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-300"
               data-testid="active-change-link">
              Supervisar en Trabajo Actual <span aria-hidden="true">&rarr;</span>
            </a>
          </div>
        </ng-container>

        <ng-template #noActiveRun>
          <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 py-1">
            <p class="text-sm text-slate-300" role="status" data-testid="active-change-idle">Sin ejecución activa en este momento</p>
            <a routerLink="/backlog" class="inline-flex min-h-10 items-center justify-center gap-1.5 self-start rounded-xl bg-slate-700 px-4 py-2 text-xs font-semibold text-slate-100 transition-colors hover:bg-slate-600 focus:outline-none focus:ring-2 focus:ring-slate-300" data-testid="active-change-backlog-link">
              Iniciar o consultar en Backlog <span aria-hidden="true">&rarr;</span>
            </a>
          </div>
        </ng-template>
      </section>
    </div>
  `
})
export class DashboardComponent {
  readonly selectedDimension = signal<'autonomy' | 'time' | 'cost'>('autonomy');
  readonly pipelineStages = PIPELINE_STAGES;
  readonly activeRun = computed(() => {
    const projectId = this.refresh.activeProject()?.project_id;
    return this.refresh.runs().find(run => run.is_active && (!projectId || run.project_id === projectId)) ?? null;
  });
  readonly activeRequest = computed(() => {
    const requestId = this.activeRun()?.request_id;
    if (!requestId) return null;
    return [...this.refresh.allRequests(), ...this.refresh.closedRequests()]
      .find(request => request.request_id === requestId) ?? null;
  });

  constructor(public refresh: RefreshService) {}

  activeStageIndex(run: OrchestrationRun): number {
    return this.pipelineStages.findIndex(stage => stage.key === run.stage);
  }

  stageLabel(stageKey: string): string {
    return this.pipelineStages.find(stage => stage.key === stageKey)?.label ?? stageKey;
  }

  stageIllustrationPath(stageKey: string): string | null {
    return getStageIllustrationPath(stageKey);
  }

  runStatusClass(status: string): string {
    switch (status) {
      case 'SUCCEEDED':
      case 'COMPLETED':
        return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20';
      case 'RUNNING':
      case 'IN_PROGRESS':
        return 'bg-sky-500/10 text-sky-400 border-sky-500/20';
      case 'FAILED':
      case 'ERRORED':
        return 'bg-rose-500/10 text-rose-400 border-rose-500/20';
      case 'PAUSED':
      case 'WAITING':
      case 'WAITING_CAPACITY':
      case 'HUMAN_REQUIRED':
        return 'bg-amber-500/10 text-amber-400 border-amber-500/20';
      default:
        return 'bg-slate-800 text-slate-300 border-slate-700';
    }
  }

  getStageBadgeClass(stageKey: string, currentStage: string): string {
    return getStageBadgeClass(stageKey, currentStage);
  }

  get projectProgressPercent(): number {
    const closed = this.refresh.closedRequests().length;
    const open = this.refresh.requests().length;
    const total = closed + open;
    return total === 0 ? 0 : Math.round((closed / total) * 100);
  }

  get projectProgressSublabel(): string {
    const closed = this.refresh.closedRequests().length;
    const open = this.refresh.requests().length;
    const total = closed + open;
    return total === 0 ? '0 solicitudes' : `${closed} de ${total} cerradas`;
  }

  private getQuota(provider: string) {
    return this.refresh.quotas().find(q => q.provider.toLowerCase() === provider.toLowerCase());
  }

  private observationDetails(quota: QuotaObservation): string {
    return `fuente ${quota.source}; observado ${quota.observed_at}`;
  }

  get codexValue(): number | null {
    const q = this.getQuota('codex');
    return q?.remaining_percent ?? null;
  }

  get codexSublabel(): string {
    const q = this.getQuota('codex');
    if (!q || q.remaining_percent == null) return q ? `Estado observado: ${q.state}; porcentaje no disponible; ${this.observationDetails(q)}` : 'No disponible (sin telemetría)';
    const model = q.model_id || 'Codex';
    return `${model} (${q.remaining_percent}% disponible; ${this.observationDetails(q)})`;
  }

  get antigravityValue(): number | null {
    const q = this.getQuota('antigravity');
    return q?.remaining_percent ?? null;
  }

  get antigravitySublabel(): string {
    const q = this.getQuota('antigravity');
    if (!q || q.remaining_percent == null) return q ? `Estado observado: ${q.state}; porcentaje no disponible; ${this.observationDetails(q)}` : 'No disponible (sin telemetría)';
    const model = q.model_id || 'Antigravity';
    return `${model} (${q.remaining_percent}% disponible; ${this.observationDetails(q)})`;
  }

  get deepseekValue(): number | null {
    const q = this.getQuota('deepseek');
    return q?.remaining_percent !== null && q?.remaining_percent !== undefined && Number.isFinite(q.remaining_percent)
      ? q.remaining_percent
      : null;
  }

  get deepseekTextValue(): string | null {
    const q = this.getQuota('deepseek');
    if (this.deepseekValue !== null || !q || q.balance === null || q.balance === undefined || !Number.isFinite(q.balance) || !q.currency?.trim()) {
      return null;
    }
    return `$${q.balance.toFixed(2)} ${q.currency.trim()}`;
  }

  get deepseekSublabel(): string {
    const q = this.getQuota('deepseek');
    if (this.deepseekTextValue) {
      return `${this.deepseekTextValue} observado; porcentaje no disponible; ${this.observationDetails(q!)}`;
    }
    return q ? `Estado observado: ${q.state}; capacidad no disponible; ${this.observationDetails(q)}` : 'No disponible (sin telemetría)';
  }

  get openrouterValue(): number | null {
    const q = this.getQuota('openrouter');
    return q?.remaining_percent ?? null;
  }

  get openrouterSublabel(): string {
    const q = this.getQuota('openrouter');
    if (q?.balance !== null && q?.balance !== undefined) {
      return `$${q.balance.toFixed(2)} ${q.currency || 'USD'} observado; porcentaje no disponible; ${this.observationDetails(q)}`;
    }
    return q ? `Estado observado: ${q.state}; saldo no disponible; ${this.observationDetails(q)}` : 'No disponible (sin telemetría)';
  }

  get currentDimensionTitle(): string {
    switch (this.selectedDimension()) {
      case 'autonomy': return 'Tasa de Autonomía (% éxito directo sin intervención humana)';
      case 'time': return 'Duración Total del Run (minutos transcurridos)';
      case 'cost': return 'Costo liquidado por proveedor / modelo';
    }
  }

  get currentDimensionUnit(): string {
    switch (this.selectedDimension()) {
      case 'autonomy': return '%';
      case 'time': return 'min';
      case 'cost': return 'USD';
    }
  }

  get chartColor(): string {
    switch (this.selectedDimension()) {
      case 'autonomy': return '#10b981';
      case 'time': return '#38bdf8';
      case 'cost': return '#f59e0b';
    }
  }

  get yMaxLabel(): string {
    switch (this.selectedDimension()) {
      case 'autonomy': return '100%';
      case 'time': return '24h';
      case 'cost': return '$100';
    }
  }

  get yMidLabel(): string {
    switch (this.selectedDimension()) {
      case 'autonomy': return '50%';
      case 'time': return '12h';
      case 'cost': return '$50';
    }
  }

  get yMinLabel(): string {
    switch (this.selectedDimension()) {
      case 'autonomy': return '0%';
      case 'time': return '0h';
      case 'cost': return '$0';
    }
  }

  get dataPoints(): Array<{ x: number; y: number; label: string; displayVal: string }> {
    if (this.selectedDimension() === 'cost') {
      return toDashboardCostChartPoints(this.refresh.cost().series);
    }
    const runs = this.refresh.runs().slice(0, 5).reverse();
    if (runs.length === 0) {
      return [];
    }

    const step = 500 / Math.max(1, (runs.length - 1) || 1);
    return runs.map((r, i) => {
      const x = runs.length === 1 ? 300 : 70 + (i * step);
      let y = 80;
      let displayVal = '';

      if (this.selectedDimension() === 'autonomy') {
        const isSuccess = r.status === 'COMPLETED' || r.status === 'SUCCEEDED';
        const autonomyPct = (r as any).autonomy_percent ?? (isSuccess ? 100 : 0);
        y = Math.max(20, Math.round(145 - ((autonomyPct / 100) * 125)));
        displayVal = `${autonomyPct}%`;
      } else if (this.selectedDimension() === 'time') {
        const t1 = r.created_at ? new Date(r.created_at).getTime() : 0;
        const t2 = r.updated_at ? new Date(r.updated_at).getTime() : Date.now();
        const dm = Math.max(1, Math.round((t2 - t1) / 60000));
        displayVal = dm >= 60 ? `${(dm / 60).toFixed(1)}h` : `${dm}m`;
        y = Math.max(20, Math.round(145 - Math.min(1, dm / 1440) * 125));
      }

      const shortId = r.run_id.length > 8 ? r.run_id.substring(0, 8) : r.run_id;
      const label = r.change_name ? (r.change_name.length > 12 ? r.change_name.substring(0, 10) + '..' : r.change_name) : shortId;
      return { x, y, label, displayVal };
    });
  }

  get chartPoints(): string {
    return this.dataPoints.map(p => `${p.x},${p.y}`).join(' ');
  }
}
