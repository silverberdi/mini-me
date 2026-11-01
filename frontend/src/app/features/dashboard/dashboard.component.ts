import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RefreshService } from '../../core/refresh.service';
import { AnalogGaugeComponent } from '../../shared/analog-gauge.component';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, AnalogGaugeComponent],
  template: `
    <div class="space-y-6">
      <!-- Overview Header -->
      <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-4 bg-slate-800/40 p-6 rounded-2xl border border-slate-700/50 backdrop-blur-sm">
        <div>
          <h1 class="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
            <span>Visión General</span>
            <span *ngIf="refresh.activeProject()" class="text-sm font-semibold px-2.5 py-0.5 rounded-full bg-sky-500/10 text-sky-400 border border-sky-500/20">
              {{ refresh.activeProject()?.project_id }}
            </span>
          </h1>
          <p class="text-sm text-slate-400 mt-1">Estado de ejecución, orquestación y métricas operativas del centro de control.</p>
        </div>
        <div class="flex items-center gap-3">
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

      <!-- 270-degree Analog Gauges Grid for 4 Providers -->
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <app-analog-gauge
          [label]="'Codex'"
          [value]="codexValue"
          [unit]="'%'"
          [color]="codexColor"
          [sublabel]="codexSublabel">
        </app-analog-gauge>

        <app-analog-gauge
          [label]="'Antigravity'"
          [value]="antigravityValue"
          [unit]="'%'"
          [color]="antigravityColor"
          [sublabel]="antigravitySublabel">
        </app-analog-gauge>

        <app-analog-gauge
          [label]="'DeepSeek'"
          [value]="deepseekValue"
          [unit]="'%'"
          [color]="deepseekColor"
          [sublabel]="deepseekSublabel">
        </app-analog-gauge>

        <app-analog-gauge
          [label]="'OpenRouter'"
          [value]="openrouterValue"
          [unit]="'%'"
          [color]="openrouterColor"
          [sublabel]="openrouterSublabel">
        </app-analog-gauge>
      </div>

      <!-- Active Runs & Recent Activity Grid -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- Active Runs Card -->
        <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 p-6 backdrop-blur-sm">
          <div class="flex items-center justify-between mb-4">
            <h2 class="text-lg font-semibold text-white">Runs de Orquestación</h2>
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
                        'bg-amber-500/10 text-amber-400 border border-amber-500/20': run.status === 'PAUSED' || run.status === 'WAITING'
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
            <h2 class="text-lg font-semibold text-white">Solicitudes Recientes</h2>
            <span class="text-xs font-mono text-slate-400">{{ refresh.requests().length }} solicitudes</span>
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
  constructor(public refresh: RefreshService) {}

  get runningCount(): number {
    return this.refresh.runs().filter(r => r.status === 'RUNNING' || r.status === 'IN_PROGRESS').length;
  }

  get successRate(): number {
    const runs = this.refresh.runs();
    if (runs.length === 0) return 100;
    const completed = runs.filter(r => r.status === 'SUCCEEDED' || r.status === 'COMPLETED').length;
    return Math.round((completed / runs.length) * 100);
  }

  private getQuota(provider: string) {
    return this.refresh.quotas().find(q => q.provider.toLowerCase() === provider.toLowerCase());
  }

  get codexValue(): number {
    const q = this.getQuota('codex');
    return q?.remaining_percent ?? 93;
  }

  get codexColor(): 'sky' | 'emerald' | 'amber' | 'rose' {
    const v = this.codexValue;
    if (v < 20) return 'rose';
    if (v < 50) return 'amber';
    return 'emerald';
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

  get antigravityColor(): 'sky' | 'emerald' | 'amber' | 'rose' {
    const v = this.antigravityValue;
    if (v < 20) return 'rose';
    if (v < 50) return 'amber';
    return 'sky';
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

  get deepseekColor(): 'sky' | 'emerald' | 'amber' | 'rose' {
    const v = this.deepseekValue;
    if (v < 20) return 'rose';
    if (v < 50) return 'amber';
    return 'emerald';
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

  get openrouterColor(): 'sky' | 'emerald' | 'amber' | 'rose' {
    const v = this.openrouterValue;
    if (v < 20) return 'rose';
    if (v < 50) return 'amber';
    return 'sky';
  }

  get openrouterSublabel(): string {
    const q = this.getQuota('openrouter');
    const bal = q?.balance !== null && q?.balance !== undefined ? q.balance : 18.43;
    return `$${bal.toFixed(2)} de $30.00 USD (${this.openrouterValue}% disponible)`;
  }
}
