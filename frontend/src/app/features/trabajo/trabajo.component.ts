import { Component, computed, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router } from '@angular/router';
import { RefreshService } from '../../core/refresh.service';
import { ApiService } from '../../core/api.service';
import { OrchestrationRun } from '../../core/models';

@Component({
  selector: 'app-trabajo',
  standalone: true,
  imports: [CommonModule, RouterModule],
  template: `
    <div class="space-y-6">
      <!-- Header -->
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-slate-800/40 p-6 rounded-2xl border border-slate-700/50 backdrop-blur-sm">
        <div>
          <h1 class="text-2xl font-bold tracking-tight text-white flex items-center gap-3">
            <span>Cola de Trabajo</span>
            <span *ngIf="refresh.activeProject()" class="text-sm font-semibold px-2.5 py-0.5 rounded-full bg-sky-500/10 text-sky-400 border border-sky-500/20">
              {{ refresh.activeProject().project_id }}
            </span>
          </h1>
          <p class="text-sm text-slate-400 mt-1">Supervisión operativa de ejecuciones activas, historial de entregas y control del planificador.</p>
        </div>

        <div class="flex items-center gap-2">
          <button
            (click)="toggleSystemPause()"
            [disabled]="isActionRunning()"
            class="px-4 py-2 rounded-xl border text-xs font-semibold tracking-wide transition-all shadow-md flex items-center gap-2 cursor-pointer"
            [ngClass]="isSystemPaused() ? 'bg-emerald-600 hover:bg-emerald-500 text-white border-emerald-500/30' : 'bg-amber-600/20 hover:bg-amber-600/30 text-amber-300 border-amber-500/30'">
            <span>{{ isSystemPaused() ? '▶ Reanudar mini me' : '⏸ Pausa Diferida' }}</span>
          </button>
        </div>
      </div>

      <!-- Action Feedback Banner -->
      <div *ngIf="actionMsg()"
           class="p-4 rounded-xl text-xs font-mono flex items-center justify-between"
           [ngClass]="actionOk() ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'">
        <span>{{ actionMsg() }}</span>
        <button (click)="actionMsg.set(null)" class="text-slate-400 hover:text-white ml-2">✕</button>
      </div>

      <!-- Operational Cards Grid (3 Paneles) -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
        <!-- 1. En Ejecución -->
        <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 p-6 backdrop-blur-sm space-y-3 flex flex-col justify-between">
          <div>
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs uppercase font-mono tracking-wider font-semibold text-sky-400">En Ejecución</span>
              <span class="w-2.5 h-2.5 rounded-full" [ngClass]="activeRun() ? 'bg-sky-400 animate-pulse' : 'bg-slate-600'"></span>
            </div>
            <div *ngIf="activeRun()" class="space-y-1.5">
              <div class="font-mono text-sm font-bold text-white truncate">{{ activeRun()?.run_id }}</div>
              <div class="text-xs text-slate-300 truncate">{{ activeRun()?.change_name || 'Sin cambio asignado' }}</div>
              <div class="inline-block px-2 py-0.5 text-[11px] rounded bg-slate-800 text-sky-300 border border-slate-700 font-mono mt-1">
                Etapa: {{ activeRun()?.stage }}
              </div>
            </div>
            <div *ngIf="!activeRun()" class="text-xs text-slate-500 py-3">
              No hay Run en ejecución activa en este momento.
            </div>
          </div>

          <div *ngIf="activeRun()" class="pt-3 border-t border-slate-800">
            <button
              (click)="openRun(activeRun()!.run_id, activeRun()!.project_id)"
              class="w-full py-2 rounded-xl bg-sky-600 hover:bg-sky-500 text-white font-semibold text-xs transition-colors flex items-center justify-center gap-1.5 cursor-pointer">
              <span>Supervisar en Trabajo Actual</span>
              <span>&rarr;</span>
            </button>
          </div>
        </div>

        <!-- 2. Último Terminado -->
        <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 p-6 backdrop-blur-sm space-y-3 flex flex-col justify-between">
          <div>
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs uppercase font-mono tracking-wider font-semibold text-emerald-400">Último Terminado</span>
              <span class="text-xs font-mono text-slate-500">Histórico</span>
            </div>
            <div *ngIf="lastCompletedRun()" class="space-y-1.5">
              <div class="font-mono text-sm font-bold text-white truncate">{{ lastCompletedRun()?.run_id }}</div>
              <div class="text-xs text-slate-300 truncate">{{ lastCompletedRun()?.change_name || 'Sin cambio' }}</div>
              <div class="flex items-center gap-2 mt-1">
                <span class="px-2 py-0.5 text-[11px] font-semibold rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  {{ lastCompletedRun()?.status }}
                </span>
                <span class="text-[11px] text-slate-500 font-mono">{{ lastCompletedRun()?.updated_at || 'Reciente' }}</span>
              </div>
            </div>
            <div *ngIf="!lastCompletedRun()" class="text-xs text-slate-500 py-3">
              Sin entregas terminadas verificables aún.
            </div>
          </div>

          <div *ngIf="lastCompletedRun()" class="pt-3 border-t border-slate-800">
            <button
              (click)="openRun(lastCompletedRun()!.run_id, lastCompletedRun()!.project_id)"
              class="w-full py-2 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 font-semibold text-xs transition-colors cursor-pointer">
              Ver Evidencias y Diagnóstico
            </button>
          </div>
        </div>

        <!-- 3. Siguiente en Cola -->
        <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 p-6 backdrop-blur-sm space-y-3 flex flex-col justify-between">
          <div>
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs uppercase font-mono tracking-wider font-semibold text-amber-400">Siguiente en Cola (FIFO)</span>
              <span class="text-xs font-mono text-slate-500">GitHub</span>
            </div>
            <div *ngIf="nextEligibleRequest()" class="space-y-1.5">
              <div class="text-xs font-mono font-bold text-sky-400">#{{ nextEligibleRequest()?.issue_number }}</div>
              <div class="text-sm font-semibold text-white truncate">{{ nextEligibleRequest()?.title }}</div>
              <p class="text-xs text-slate-400 line-clamp-2">{{ nextEligibleRequest()?.body || 'Sin descripción adicional' }}</p>
            </div>
            <div *ngIf="!nextEligibleRequest()" class="text-xs text-slate-500 py-3">
              No hay solicitudes pendientes elegibles en la cola FIFO.
            </div>
          </div>

          <div class="pt-3 border-t border-slate-800 text-[11px] text-slate-500 font-mono">
            La elegibilidad se determina estrictamente en el backend.
          </div>
        </div>
      </div>

      <!-- Execution History Table -->
      <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 overflow-hidden backdrop-blur-sm shadow-xl">
        <div class="p-4 border-b border-slate-700/60 flex items-center justify-between">
          <h2 class="text-base font-semibold text-white">Historial de Ejecuciones del Proyecto</h2>
          <span class="text-xs font-mono text-slate-400">{{ refresh.runs().length }} ejecuciones registradas</span>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-left text-sm text-slate-300">
            <thead class="bg-slate-900/60 text-xs uppercase font-semibold text-slate-400 border-b border-slate-700/60">
              <tr>
                <th class="px-6 py-3.5">Run ID</th>
                <th class="px-6 py-3.5">Proyecto</th>
                <th class="px-6 py-3.5">Cambio OpenSpec</th>
                <th class="px-6 py-3.5">Etapa (Stage)</th>
                <th class="px-6 py-3.5">Estado</th>
                <th class="px-6 py-3.5">Última Actualización</th>
                <th class="px-6 py-3.5 text-right">Acción</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800/60">
              <tr *ngFor="let run of refresh.runs()"
                  (click)="openRun(run.run_id, run.project_id)"
                  class="hover:bg-slate-800/50 transition-colors cursor-pointer group">
                <td class="px-6 py-4 font-mono text-xs font-bold text-sky-400 group-hover:underline">{{ run.run_id }}</td>
                <td class="px-6 py-4 font-medium text-slate-200">{{ run.project_id }}</td>
                <td class="px-6 py-4 text-xs font-mono text-slate-300">{{ run.change_name || 'N/A' }}</td>
                <td class="px-6 py-4">
                  <span class="px-2.5 py-1 text-xs font-medium rounded-full bg-slate-800 border border-slate-700 text-slate-300">
                    {{ run.stage }}
                  </span>
                </td>
                <td class="px-6 py-4">
                  <span class="px-2.5 py-1 text-xs font-semibold rounded-lg"
                        [ngClass]="{
                          'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20': run.status === 'SUCCEEDED' || run.status === 'COMPLETED',
                          'bg-sky-500/10 text-sky-400 border border-sky-500/20': run.status === 'RUNNING' || run.status === 'IN_PROGRESS',
                          'bg-rose-500/10 text-rose-400 border border-rose-500/20': run.status === 'FAILED' || run.status === 'ERRORED',
                          'bg-amber-500/10 text-amber-400 border border-amber-500/20': run.status === 'PAUSED' || run.status === 'WAITING' || run.status === 'HUMAN_REQUIRED'
                        }">
                    {{ run.status }}
                  </span>
                </td>
                <td class="px-6 py-4 text-xs text-slate-500 font-mono">{{ run.updated_at || 'Reciente' }}</td>
                <td class="px-6 py-4 text-right">
                  <span class="text-xs text-sky-400 group-hover:text-sky-300 font-semibold flex items-center justify-end gap-1">
                    <span>Supervisar</span>
                    <span>&rarr;</span>
                  </span>
                </td>
              </tr>

              <tr *ngIf="refresh.runs().length === 0">
                <td colspan="7" class="px-6 py-12 text-center text-slate-500 text-sm">
                  No se encontraron ejecuciones registradas para el proyecto actual.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `
})
export class TrabajoComponent {
  private router = inject(Router);
  private api = inject(ApiService);
  public refresh = inject(RefreshService);

  readonly isActionRunning = signal<boolean>(false);
  readonly actionMsg = signal<string | null>(null);
  readonly actionOk = signal<boolean>(false);
  readonly isSystemPaused = signal<boolean>(false);

  readonly activeRun = computed(() => {
    const runs = this.refresh.runs();
    return runs.find(r => r.is_active || r.status === 'RUNNING' || r.status === 'IN_PROGRESS' || r.status === 'HUMAN_REQUIRED') || null;
  });

  readonly lastCompletedRun = computed(() => {
    const runs = this.refresh.runs();
    return runs.filter(r => !r.is_active && (r.status === 'COMPLETED' || r.status === 'SUCCEEDED' || r.status === 'FAILED'))[0] || null;
  });

  readonly nextEligibleRequest = computed(() => {
    const reqs = this.refresh.requests();
    return reqs.find(r => r.status === 'ELIGIBLE') || null;
  });

  openRun(runId: string, projectId: string) {
    void this.router.navigate(['/trabajo-actual'], {
      queryParams: { run: runId, project: projectId }
    });
  }

  async toggleSystemPause() {
    this.isActionRunning.set(true);
    this.actionMsg.set(null);

    const willPause = !this.isSystemPaused();
    const endpoint = willPause ? '/api/v1/system/pause' : '/api/v1/system/resume';
    const msgConfirm = willPause
      ? '¿Deseas solicitar una pausa global diferida de mini me? Los ciclos activos concluirán limpiamente antes de detenerse.'
      : '¿Deseas reanudar la ejecución global de mini me?';

    if (!confirm(msgConfirm)) {
      this.isActionRunning.set(false);
      return;
    }

    try {
      const res = await this.api.post(endpoint, {});
      if (res.ok) {
        this.isSystemPaused.set(willPause);
        this.actionOk.set(true);
        this.actionMsg.set(willPause ? 'Pausa diferida solicitada exitosamente.' : 'mini me reanudado exitosamente.');
        await this.refresh.read();
      } else {
        this.actionOk.set(false);
        this.actionMsg.set(`Error al cambiar estado de ejecución: ${res.error || 'Error'}`);
      }
    } catch (e: any) {
      this.actionOk.set(false);
      this.actionMsg.set(`Error de conexión: ${e.message || e}`);
    } finally {
      this.isActionRunning.set(false);
    }
  }
}
