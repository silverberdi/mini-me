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
import type { OrchestrationRun, QuotaObservation, TemporalTelemetryProjection, TemporalTelemetrySeries } from '../../core/models';

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
        <p class="px-1 text-xs text-slate-400" data-testid="capacity-reference-note">Cuando no hay porcentaje informado, el saldo USD usa $20 como referencia visual del 100%.</p>
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <app-analog-gauge
            label="Codex"
            unit="%"
            color="emerald"
            [value]="capacityGaugeValue('codex')"
            [max]="100"
            [textValue]="capacityTextValue('codex')"
            [detail]="capacitySecondaryDetail('codex')"
            [sublabel]="capacitySublabel('codex', 'Codex')">
          </app-analog-gauge>

          <app-analog-gauge
            label="Antigravity"
            unit="%"
            color="sky"
            [value]="capacityGaugeValue('antigravity')"
            [max]="100"
            [textValue]="capacityTextValue('antigravity')"
            [detail]="capacitySecondaryDetail('antigravity')"
            [sublabel]="capacitySublabel('antigravity', 'Antigravity')">
          </app-analog-gauge>

          <app-analog-gauge
            label="DeepSeek"
            unit="%"
            color="amber"
            [value]="capacityGaugeValue('deepseek')"
            [max]="100"
            [textValue]="capacityTextValue('deepseek')"
            [detail]="capacitySecondaryDetail('deepseek')"
            [sublabel]="capacitySublabel('deepseek', 'DeepSeek')">
          </app-analog-gauge>

          <app-analog-gauge
            label="OpenRouter"
            unit="%"
            color="sky"
            [value]="capacityGaugeValue('openrouter')"
            [max]="100"
            [textValue]="capacityTextValue('openrouter')"
            [detail]="capacitySecondaryDetail('openrouter')"
            [sublabel]="capacitySublabel('openrouter', 'OpenRouter')">
          </app-analog-gauge>
        </div>
      </div>

      <!-- Temporal multi-series telemetry. Interaction state is intentionally local. -->
      <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 p-6 backdrop-blur-sm space-y-4 shadow-xl">
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-700/60 pb-4">
          <div>
            <h2 class="text-base font-bold text-white flex items-center gap-2">
              <span>Gráfica de Líneas de Efectividad</span>
              <span class="text-xs font-mono font-normal text-slate-400">(Tres Dimensiones Independientes)</span>
            </h2>
            <p class="text-xs text-slate-400 mt-0.5">Tendencias verificables de los últimos {{ selectedWindowDays }} días; las esperas humanas quedan excluidas del tiempo activo.</p>
          </div>
          <div class="flex flex-wrap items-center gap-2 self-start sm:self-auto">
            <div class="flex items-center gap-1 bg-slate-900/80 p-1 rounded-xl border border-slate-800" role="group" aria-label="Rango temporal">
              <button
                *ngFor="let days of availableWindowDays"
                (click)="setWindowDays(days)"
                [ngClass]="selectedWindowDays === days ? 'bg-indigo-600 text-white font-bold shadow' : 'text-slate-400 hover:text-slate-200 font-medium'"
                class="px-2.5 py-1 text-xs rounded-lg transition-all cursor-pointer font-mono"
                [attr.aria-pressed]="selectedWindowDays === days"
                [attr.data-testid]="'telemetry-window-' + days + 'd'">
                {{ days }}d
              </button>
            </div>
            <div class="flex flex-wrap items-center gap-1.5 bg-slate-900/80 p-1 rounded-xl border border-slate-800">
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
        </div>

        <div class="p-4 rounded-xl bg-slate-950/70 border border-slate-800 space-y-3" data-testid="temporal-telemetry-chart">
          <div class="flex items-center justify-between text-xs font-mono">
            <span class="text-slate-300 font-semibold flex items-center gap-2">
              <span class="w-2.5 h-2.5 rounded-full" [style.background-color]="selectedSeriesColor"></span>
              {{ currentDimensionTitle }}
            </span>
            <span class="text-slate-400 font-mono">Unidad: {{ currentProjection?.units || currentDimensionUnit }}</span>
          </div>

          <div class="relative w-full h-52">
            <div *ngIf="!currentProjection || currentProjection.no_data" class="h-full flex flex-col items-center justify-center text-center p-6 text-slate-500 space-y-1" role="status" aria-live="polite">
              <span class="text-sm font-medium text-slate-400">{{ selectedDimension() === 'cost' ? 'Sin datos de costo liquidado' : 'Sin datos verificables para esta dimensión' }}</span>
              <span class="text-xs font-mono">{{ selectedDimension() === 'cost' ? 'No existe un importe verificable en el ledger.' : 'No se muestran ceros, estimaciones ni puntos inventados.' }}</span>
            </div>

            <svg *ngIf="currentProjection && !currentProjection.no_data" viewBox="0 0 600 170" preserveAspectRatio="none" class="w-full h-full overflow-visible" aria-label="Series temporales de telemetría">
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
                *ngFor="let series of visibleSeries"
                [attr.points]="seriesPoints(series)"
                [attr.stroke]="series.color"
                [attr.opacity]="hoveredSeriesId && hoveredSeriesId !== series.series_id ? 0.22 : 1"
                [attr.data-series-id]="series.series_id"
                (mouseenter)="hoveredSeriesId = series.series_id"
                (mouseleave)="hoveredSeriesId = null"
              />

              <!-- Data Point Circles and Labels -->
              <ng-container *ngFor="let series of visibleSeries">
                <circle
                  *ngFor="let point of series.points"
                  [attr.cx]="pointX(point.timestamp)"
                  [attr.cy]="pointY(point.value)"
                  r="4"
                  [attr.fill]="series.color"
                  stroke="#0f172a"
                  stroke-width="1.5"
                  [attr.opacity]="hoveredSeriesId && hoveredSeriesId !== series.series_id ? 0.22 : 1"
                  [attr.data-point-id]="series.series_id + ':' + point.timestamp"
                  class="cursor-pointer transition-transform hover:scale-125"
                  (mouseenter)="hoveredSeriesId = series.series_id"
                  (mouseleave)="hoveredSeriesId = null"
                >
                  <title>{{ series.label }}: {{ point.value }} {{ currentProjection?.units || currentDimensionUnit }} ({{ point.timestamp }})</title>
                </circle>
              </ng-container>
            </svg>
          </div>

          <div class="flex flex-wrap gap-2" aria-label="Leyenda de series temporales">
            <div *ngFor="let series of currentProjection?.series || []" class="flex items-center gap-1 rounded-lg border border-slate-700 px-2 py-1 text-xs" [class.opacity-40]="!isSeriesVisible(series.series_id) || (hoveredSeriesId && hoveredSeriesId !== series.series_id)" (mouseenter)="hoveredSeriesId = series.series_id" (mouseleave)="hoveredSeriesId = null">
              <button type="button" class="inline-flex items-center gap-1 focus:outline-none focus:ring-2 focus:ring-sky-300" [attr.aria-pressed]="isSeriesVisible(series.series_id)" [attr.aria-label]="'Mostrar u ocultar ' + series.label" (click)="toggleSeries(series.series_id)">
                <span class="w-2.5 h-2.5 rounded-full" [style.background-color]="series.color"></span>{{ series.label }}
              </button>
              <button type="button" class="text-[10px] text-sky-300 hover:text-white" [attr.aria-label]="'Aislar ' + series.label" (click)="soloSeries(series.series_id)">Aislar</button>
            </div>
            <button type="button" class="text-xs text-slate-300 underline" (click)="restoreSeries()">Restaurar</button>
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
            <span>{{ currentProjection?.no_data ? 'Sin observaciones verificables' : (currentProjection?.axis?.length || 0) + ' buckets temporales; ' + visibleSeries.length + ' series visibles' }}</span>
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

          <div *ngIf="activeStageIndex(run) !== -1" class="grid grid-cols-2 sm:grid-cols-5 lg:grid-cols-10 gap-2" role="list" aria-label="Avance por etapas" data-testid="active-change-stage-progress">
            <div *ngFor="let stage of pipelineStages; let idx = index"
                 class="p-2.5 rounded-xl border flex flex-col items-center text-center transition-all"
                 [ngClass]="getStagePanelClass(stage.key, run.stage)"
                 [attr.aria-current]="stage.key === run.stage ? 'step' : null"
                 [attr.aria-label]="stage.label + (stage.key === run.stage ? ', etapa actual' : idx < activeStageIndex(run) ? ', completada' : ', pendiente')"
                 [title]="stage.label"
                 data-testid="active-change-stage-card"
                 role="listitem">
              <span class="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold font-mono mb-1.5"
                    [ngClass]="getStageBadgeClass(stage.key, run.stage)">
                {{ idx + 1 }}
              </span>
              <span class="text-[11px] font-semibold leading-tight line-clamp-2">
                {{ stage.label }}
              </span>
            </div>
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
  readonly availableWindowDays: readonly (7 | 14 | 30 | 90)[] = [7, 14, 30, 90] as const;
  private readonly visibleSeriesIds = signal<Set<string>>(new Set());
  hoveredSeriesId: string | null = null;
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

  get selectedWindowDays(): 7 | 14 | 30 | 90 {
    return this.refresh.telemetryWindowDays();
  }

  setWindowDays(days: 7 | 14 | 30 | 90): void {
    void this.refresh.setTelemetryWindowDays(days);
  }

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

  getStagePanelClass(stageKey: string, currentStage: string): string {
    return getStagePanelClass(stageKey, currentStage);
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

  private quotaPercent(quota: QuotaObservation | undefined): number | null {
    const value = quota?.remaining_percent;
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
  }

  private quotaBalance(quota: QuotaObservation | undefined): { amount: number; currency: string } | null {
    if (typeof quota?.balance !== 'number' || !Number.isFinite(quota.balance) || !quota.currency?.trim()) return null;
    return { amount: quota.balance, currency: quota.currency.trim().toUpperCase() };
  }

  private formatQuotaBalance(balance: { amount: number; currency: string }): string {
    const amount = balance.amount.toFixed(2);
    return balance.currency === 'USD' ? `$${amount} USD` : `${amount} ${balance.currency}`;
  }

  capacityGaugeValue(provider: string): number | null {
    const quota = this.getQuota(provider);
    const reportedPercent = this.quotaPercent(quota);
    if (reportedPercent !== null) return reportedPercent;

    const balance = this.quotaBalance(quota);
    if (balance?.currency === 'USD') return Math.min(100, Math.max(0, Math.round((balance.amount / 20) * 100)));
    return null;
  }

  capacityTextValue(provider: string): string | null {
    const quota = this.getQuota(provider);
    if (this.quotaPercent(quota) !== null) return null;

    const balance = this.quotaBalance(quota);
    return balance?.currency === 'USD' ? `${this.capacityGaugeValue(provider)}%` : null;
  }

  capacitySecondaryDetail(provider: string): string | null {
    const quota = this.getQuota(provider);
    const balance = this.quotaBalance(quota);
    if (!balance) return null;

    if (balance.currency !== 'USD') return `${this.formatQuotaBalance(balance)} observado; sin escala porcentual definida`;
    const projection = this.quotaPercent(quota) === null
      ? 'porcentaje visual con referencia USD 20 = 100%'
      : 'saldo observado; porcentaje informado por el proveedor';
    return `${this.formatQuotaBalance(balance)} observado; ${projection}`;
  }

  capacitySublabel(provider: string, fallbackModel: string): string {
    const quota = this.getQuota(provider);
    if (!quota) return 'No disponible (sin telemetría)';

    const model = quota.model_id || fallbackModel;
    const percent = this.quotaPercent(quota);
    if (percent !== null) return `${model} (${percent}% disponible; ${this.observationDetails(quota)})`;

    const balance = this.quotaBalance(quota);
    if (balance) {
      const scale = balance.currency === 'USD' ? 'arco con referencia visual USD 20 = 100%' : 'sin escala visual definida para esta moneda';
      return `${this.formatQuotaBalance(balance)} observado; ${scale}; ${this.observationDetails(quota)}`;
    }

    return `Estado observado: ${quota.state}; capacidad no disponible; ${this.observationDetails(quota)}`;
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

  get currentProjection(): TemporalTelemetryProjection | null {
    return this.refresh.temporalTelemetry()[this.selectedDimension()] ?? null;
  }

  get selectedSeriesColor(): string {
    return this.currentProjection?.series[0]?.color ?? '#38bdf8';
  }

  get visibleSeries(): TemporalTelemetrySeries[] {
    const all = this.currentProjection?.series ?? [];
    const selected = this.visibleSeriesIds();
    return selected.size ? all.filter(series => selected.has(series.series_id)) : all;
  }

  isSeriesVisible(seriesId: string): boolean {
    return this.visibleSeriesIds().size === 0 || this.visibleSeriesIds().has(seriesId);
  }

  toggleSeries(seriesId: string): void {
    const all = this.currentProjection?.series ?? [];
    const next = new Set(this.visibleSeriesIds().size ? this.visibleSeriesIds() : all.map(series => series.series_id));
    if (next.has(seriesId)) next.delete(seriesId); else next.add(seriesId);
    this.visibleSeriesIds.set(next.size === all.length ? new Set() : next);
  }

  soloSeries(seriesId: string): void {
    this.visibleSeriesIds.set(new Set([seriesId]));
  }

  restoreSeries(): void {
    this.visibleSeriesIds.set(new Set());
  }

  seriesPoints(series: TemporalTelemetrySeries): string {
    const projection = this.currentProjection;
    if (!projection || projection.axis.length < 1) return '';
    const max = Math.max(...projection.series.flatMap(item => item.points.map(point => point.value)), 1);
    return series.points.map(point => {
      const index = projection.axis.indexOf(point.timestamp);
      const x = projection.axis.length === 1 ? 300 : 70 + (index * 500 / (projection.axis.length - 1));
      const y = Math.max(20, Math.round(145 - Math.min(1, point.value / max) * 125));
      return `${x},${y}`;
    }).join(' ');
  }

  pointX(timestamp: string): number {
    const projection = this.currentProjection;
    if (!projection || projection.axis.length < 1) return 300;
    const index = projection.axis.indexOf(timestamp);
    return projection.axis.length === 1 ? 300 : Math.round(70 + (index * 500 / (projection.axis.length - 1)));
  }

  pointY(value: number): number {
    const projection = this.currentProjection;
    if (!projection) return 145;
    const max = Math.max(...projection.series.flatMap(item => item.points.map(point => point.value)), 1);
    return Math.max(20, Math.round(145 - Math.min(1, value / max) * 125));
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

}
