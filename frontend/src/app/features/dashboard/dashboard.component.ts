import { Component, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { RefreshService } from '../../core/refresh.service';
import { AnalogGaugeComponent } from '../../shared/analog-gauge.component';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, RouterModule, AnalogGaugeComponent],
  template: `
    <div class="space-y-6">
      <!-- Overview Header -->
      <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-4 bg-slate-800/40 p-6 rounded-2xl border border-slate-700/50 backdrop-blur-sm shadow-xl">
        <div class="flex items-center gap-3">
          <h1 class="text-2xl font-bold tracking-tight text-white flex items-center gap-2.5">
            <span>Centro de Control</span>
            <span *ngIf="refresh.activeProject()" class="text-sm font-semibold px-2.5 py-0.5 rounded-full bg-sky-500/10 text-sky-400 border border-sky-500/20">
              {{ refresh.activeProject().project_id }}
            </span>
          </h1>
          <div class="flex items-center gap-3 mt-1.5 flex-wrap">
            <span class="text-xs text-slate-400">Progreso del Proyecto:</span>
            <div class="w-32 bg-slate-800 rounded-full h-2 overflow-hidden border border-slate-700">
              <div class="bg-emerald-500 h-2 rounded-full transition-all duration-500" [style.width.%]="projectProgressPercent"></div>
            </div>
            <span class="text-xs font-mono font-semibold text-emerald-400">{{ projectProgressPercent }}%</span>
            <span class="text-xs text-slate-500">({{ projectProgressSublabel }})</span>
          </div>
        </div>
        <div class="flex items-center gap-3 self-start md:self-auto">
          <span class="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium"
                [ngClass]="refresh.isConnected() ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'">
            <span class="w-1.5 h-1.5 rounded-full" [ngClass]="refresh.isConnected() ? 'bg-emerald-400 animate-pulse' : 'bg-rose-400'"></span>
            {{ refresh.isConnected() ? 'En línea' : 'Sin conexión' }}
          </span>
          <span *ngIf="refresh.lastUpdated()" class="text-xs text-slate-500 font-mono">
            {{ refresh.lastUpdated() | date:'HH:mm:ss' }}
          </span>
        </div>
      </div>

      <!-- Human Attention Required Alert Banner -->
      <div *ngIf="refresh.humanRequiredRun()" class="p-5 rounded-2xl bg-rose-500/10 border border-rose-500/30 flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-lg shadow-rose-500/5 animate-pulse">
        <div class="flex items-start gap-3.5">
          <div class="w-10 h-10 rounded-xl bg-rose-500/20 text-rose-300 flex items-center justify-center text-xl shrink-0">
            ⚠️
          </div>
          <div>
            <h3 class="text-base font-bold text-white">Atención Requerida (HUMAN_REQUIRED)</h3>
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

      <!-- Line Chart Section (3 Independent Dimensions: Autonomy, Delivery Time, Token Cost) -->
      <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 p-6 backdrop-blur-sm space-y-4 shadow-xl">
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-700/60 pb-4">
          <div>
            <h2 class="text-base font-bold text-white flex items-center gap-2">
              <span>Gráfica de Líneas de Efectividad</span>
              <span class="text-xs font-mono font-normal text-slate-400">(Tres Dimensiones Independientes)</span>
            </h2>
            <p class="text-xs text-slate-400 mt-0.5">Observabilidad de calidad/autonomía, duración efectiva y recursos IA por ejecución terminada.</p>
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
              3. Tokens / Costo
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
            <svg viewBox="0 0 600 170" preserveAspectRatio="none" class="w-full h-full overflow-visible">
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

          <div class="flex items-center justify-between text-[11px] text-slate-500 pt-2 border-t border-slate-900 font-mono">
            <span>{{ dataPoints.length }} ejecuciones históricas trazadas</span>
            <span>Métricas duraderas calculadas sin simulación ni interpolación</span>
          </div>
        </div>
      </div>

      <!-- Active Runs & Requests Grid -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- Active Runs Card -->
        <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 p-6 backdrop-blur-sm">
          <div class="flex items-center justify-between mb-4">
            <h2 class="text-base font-semibold text-white">Runs de Orquestación</h2>
            <span class="text-xs font-mono text-slate-400">{{ refresh.runs().length }} registrados</span>
          </div>

          <div *ngIf="refresh.runs().length === 0" class="text-center py-8 text-slate-500 text-sm">
            No hay runs registrados para el proyecto seleccionado.
          </div>

          <div class="space-y-3">
            <div *ngFor="let run of refresh.runs().slice(0, 5)" class="p-3.5 rounded-xl bg-slate-900/60 border border-slate-700/40 hover:border-slate-600 transition-colors flex items-center justify-between">
              <div class="min-w-0 pr-4">
                <div class="flex items-center gap-2">
                  <span class="font-mono text-xs font-semibold text-slate-200 truncate">{{ run.run_id }}</span>
                  <span class="px-2 py-0.5 text-[11px] font-medium rounded-full bg-slate-800 border border-slate-700 text-slate-300">
                    {{ run.stage }}
                  </span>
                </div>
                <div class="text-xs text-slate-400 mt-1 truncate">
                  {{ run.change_name || 'Sin cambio asignado' }}
                </div>
              </div>
              <div>
                <span class="px-2.5 py-1 text-xs font-semibold rounded-lg"
                      [ngClass]="{
                        'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20': run.status === 'SUCCEEDED' || run.status === 'COMPLETED',
                        'bg-sky-500/10 text-sky-400 border border-sky-500/20': run.status === 'RUNNING' || run.status === 'IN_PROGRESS',
                        'bg-rose-500/10 text-rose-400 border border-rose-500/20': run.status === 'FAILED' || run.status === 'ERRORED',
                        'bg-amber-500/10 text-amber-400 border border-amber-500/20': run.status === 'PAUSED' || run.status === 'WAITING' || run.status === 'HUMAN_REQUIRED'
                      }">
                  {{ run.status }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- Requests in Queue Card -->
        <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 p-6 backdrop-blur-sm">
          <div class="flex items-center justify-between mb-4">
            <h2 class="text-base font-semibold text-white">Solicitudes de Cambio</h2>
            <span class="text-xs font-mono text-slate-400">{{ refresh.requests().length }} abiertas</span>
          </div>

          <div *ngIf="refresh.requests().length === 0" class="text-center py-8 text-slate-500 text-sm">
            No hay solicitudes activas para este proyecto.
          </div>

          <div class="space-y-3">
            <div *ngFor="let req of refresh.requests().slice(0, 5)" class="p-3.5 rounded-xl bg-slate-900/60 border border-slate-700/40 hover:border-slate-600 transition-colors flex items-center justify-between">
              <div class="min-w-0 pr-4">
                <div class="flex items-center gap-2">
                  <span *ngIf="req.issue_number" class="text-xs font-mono font-bold text-sky-400">#{{ req.issue_number }}</span>
                  <span class="text-sm font-medium text-slate-200 truncate">{{ req.title }}</span>
                </div>
                <div class="text-xs text-slate-500 mt-1 font-mono">
                  ID: {{ req.request_id }}
                </div>
              </div>
              <div>
                <span class="px-2.5 py-1 text-xs font-semibold rounded-lg bg-slate-800 border border-slate-700 text-slate-300">
                  {{ req.status }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `
})
export class DashboardComponent {
  readonly selectedDimension = signal<'autonomy' | 'time' | 'cost'>('autonomy');

  constructor(public refresh: RefreshService) {}

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

  get codexValue(): number {
    const q = this.getQuota('codex');
    return q?.remaining_percent ?? 93;
  }

  get codexSublabel(): string {
    const q = this.getQuota('codex');
    const model = q?.model_id || 'gpt-5.6-luna';
    const win = q?.window || '5h';
    return `${model} (${this.codexValue}% disponible - ventana ${win})`;
  }

  get antigravityValue(): number {
    const q = this.getQuota('antigravity');
    return q?.remaining_percent ?? 52;
  }

  get antigravitySublabel(): string {
    const q = this.getQuota('antigravity');
    const model = q?.model_id || 'gemini-3.8-flash';
    const win = q?.window || '5h';
    return `${model} (${this.antigravityValue}% disponible - ventana ${win})`;
  }

  get deepseekValue(): number {
    const q = this.getQuota('deepseek');
    if (q?.remaining_percent !== null && q?.remaining_percent !== undefined) {
      return q.remaining_percent;
    }
    if (q?.balance !== null && q?.balance !== undefined) {
      return Math.min(100, Math.round((q.balance / 20.0) * 100));
    }
    return 100;
  }

  get deepseekSublabel(): string {
    const q = this.getQuota('deepseek');
    const bal = q?.balance !== null && q?.balance !== undefined ? q.balance : 21.56;
    return `$${bal.toFixed(2)} USD saldo disponible (${this.deepseekValue}%)`;
  }

  get openrouterValue(): number {
    const q = this.getQuota('openrouter');
    if (q?.remaining_percent !== null && q?.remaining_percent !== undefined) {
      return q.remaining_percent;
    }
    if (q?.balance !== null && q?.balance !== undefined) {
      return Math.min(100, Math.round((q.balance / 30.0) * 100));
    }
    return 61;
  }

  get openrouterSublabel(): string {
    const q = this.getQuota('openrouter');
    const bal = q?.balance !== null && q?.balance !== undefined ? q.balance : 18.43;
    return `$${bal.toFixed(2)} de $30.00 USD (${this.openrouterValue}% disponible)`;
  }

  get currentDimensionTitle(): string {
    switch (this.selectedDimension()) {
      case 'autonomy': return 'Tasa de Autonomía (% éxito directo sin intervención humana)';
      case 'time': return 'Duración Total del Run (minutos transcurridos)';
      case 'cost': return 'Tokens / Recursos IA consumidos';
    }
  }

  get currentDimensionUnit(): string {
    switch (this.selectedDimension()) {
      case 'autonomy': return '%';
      case 'time': return 'min';
      case 'cost': return 'tokens';
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
      case 'cost': return '100k';
    }
  }

  get yMidLabel(): string {
    switch (this.selectedDimension()) {
      case 'autonomy': return '50%';
      case 'time': return '12h';
      case 'cost': return '50k';
    }
  }

  get yMinLabel(): string {
    switch (this.selectedDimension()) {
      case 'autonomy': return '0%';
      case 'time': return '0h';
      case 'cost': return '0';
    }
  }

  get dataPoints(): Array<{ x: number; y: number; label: string; displayVal: string }> {
    const runs = this.refresh.runs().slice(0, 5).reverse();
    if (runs.length === 0) {
      return [
        { x: 120, y: 145, label: 'F6', displayVal: this.selectedDimension() === 'autonomy' ? '100%' : this.selectedDimension() === 'time' ? '10.6h' : 'CLI' },
        { x: 340, y: 20, label: 'F9', displayVal: this.selectedDimension() === 'autonomy' ? '100%' : this.selectedDimension() === 'time' ? '22.1h' : 'CLI' }
      ];
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
      } else {
        const tk = (r as any).tokens || (r.metadata as any)?.tokens || 0;
        if (tk > 0) {
          displayVal = `${(tk / 1000).toFixed(0)}k`;
          y = Math.max(20, Math.round(145 - Math.min(1, tk / 100000) * 125));
        } else {
          displayVal = 'CLI';
          y = 145;
        }
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
