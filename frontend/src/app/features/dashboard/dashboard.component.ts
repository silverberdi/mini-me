import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RefreshService } from '../../core/refresh.service';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="space-y-6">
      <!-- Overview Header -->
      <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-4 bg-slate-800/40 p-6 rounded-2xl border border-slate-700/50 backdrop-blur-sm">
        <div>
          <h1 class="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
            <span>Visión General</span>
            <span *ngIf="refresh.activeProject()" class="text-sm font-semibold px-2.5 py-0.5 rounded-full bg-sky-500/10 text-sky-400 border border-sky-500/20">
              {{ refresh.activeProject().project_id }}
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

      <!-- Compact observed capacity cards -->
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <article *ngFor="let quota of refresh.quotas()" class="capacity-card" [attr.aria-label]="quota.provider + ' capacity'">
          <div class="flex items-center justify-between gap-2">
            <h2 class="font-semibold text-slate-100 capitalize">{{ quota.provider }}</h2>
            <span class="status-badge" [attr.data-state]="quota.state">{{ quota.state }}</span>
          </div>
          <div class="mt-4 h-2 rounded-full bg-slate-700 overflow-hidden" role="progressbar" aria-valuemin="0" aria-valuemax="100" [attr.aria-valuenow]="quota.remaining_percent ?? null">
            <div class="h-full bg-sky-400 transition-all" [style.width.%]="quota.remaining_percent ?? 0"></div>
          </div>
          <p class="mt-2 text-xs text-slate-400">{{ quota.remaining_percent === null || quota.remaining_percent === undefined ? 'Capacidad no verificada' : quota.remaining_percent + '% disponible' }}</p>
          <p *ngIf="quota.reset_at" class="text-xs text-slate-500">Reset: {{ quota.reset_at | date:'short' }}</p>
        </article>
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

}
