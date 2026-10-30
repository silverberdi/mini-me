import { Component, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RefreshService } from '../../core/refresh.service';

@Component({
  selector: 'app-trabajo-actual',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="space-y-6">
      <div class="bg-slate-800/40 p-6 rounded-2xl border border-slate-700/50 backdrop-blur-sm">
        <h1 class="text-2xl font-bold tracking-tight text-white">Trabajo Actual</h1>
        <p class="text-sm text-slate-400 mt-1">Detalle del Run activo en ejecución y trazabilidad en tiempo real.</p>
      </div>

      <div *ngIf="!activeRun()" class="bg-slate-800/30 rounded-2xl border border-slate-700/40 p-12 text-center">
        <div class="w-12 h-12 rounded-full bg-slate-800 flex items-center justify-center mx-auto mb-4 text-slate-500">
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
        </div>
        <h3 class="text-base font-semibold text-slate-300">No hay un Run en ejecución en este momento</h3>
        <p class="text-sm text-slate-500 mt-1 max-w-sm mx-auto">Selecciona un proyecto con una ejecución activa o inicia un nuevo ciclo desde el Backlog.</p>
      </div>

      <div *ngIf="activeRun()" class="space-y-6">
        <!-- Main Run Header -->
        <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 p-6 backdrop-blur-sm">
          <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <div class="flex items-center gap-3">
                <span class="text-xs font-mono font-bold px-2.5 py-1 rounded-md bg-sky-500/10 text-sky-400 border border-sky-500/20">
                  {{ activeRun()?.run_id }}
                </span>
                <span class="px-2.5 py-1 text-xs font-semibold rounded-lg bg-sky-500/20 text-sky-300 border border-sky-500/30">
                  {{ activeRun()?.status }}
                </span>
              </div>
              <h2 class="text-xl font-bold text-white mt-2">{{ activeRun()?.change_name || 'Sin cambio OpenSpec asignado' }}</h2>
              <p class="text-xs text-slate-400 font-mono mt-1">Proyecto: {{ activeRun()?.project_id }} | Request ID: {{ activeRun()?.request_id || 'N/A' }}</p>
            </div>
            <div>
              <span class="px-3 py-1.5 rounded-xl bg-slate-900 border border-slate-700 text-sm font-semibold text-slate-200">
                Stage: {{ activeRun()?.stage }}
              </span>
            </div>
          </div>
        </div>

        <!-- Details Grid -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 p-6 backdrop-blur-sm space-y-4">
            <h3 class="text-base font-semibold text-white">Agente & Harness</h3>
            <div class="space-y-3 text-sm">
              <div class="flex justify-between py-2 border-b border-slate-700/40">
                <span class="text-slate-400">Agente Activo:</span>
                <span class="font-mono text-slate-200">{{ activeRun()?.active_agent_id || 'Autónomo / Ninguno' }}</span>
              </div>
              <div class="flex justify-between py-2 border-b border-slate-700/40">
                <span class="text-slate-400">Inicio de Ejecución:</span>
                <span class="font-mono text-slate-200">{{ activeRun()?.created_at || 'N/A' }}</span>
              </div>
              <div class="flex justify-between py-2 border-b border-slate-700/40">
                <span class="text-slate-400">Última Transición:</span>
                <span class="font-mono text-slate-200">{{ activeRun()?.updated_at || 'N/A' }}</span>
              </div>
            </div>
          </div>

          <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 p-6 backdrop-blur-sm space-y-4">
            <h3 class="text-base font-semibold text-white">Diagnóstico & Errores</h3>
            <div *ngIf="activeRun()?.error_detail" class="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs font-mono">
              {{ activeRun()?.error_detail }}
            </div>
            <div *ngIf="!activeRun()?.error_detail" class="p-4 rounded-xl bg-slate-900/60 border border-slate-700/40 text-slate-400 text-sm">
              La ejecución procede con normalidad sin errores reportados por el supervisor.
            </div>
          </div>
        </div>
      </div>
    </div>
  `
})
export class TrabajoActualComponent {
  constructor(public refresh: RefreshService) {}

  readonly activeRun = computed(() => {
    const runs = this.refresh.runs();
    return runs.find(r => r.status === 'RUNNING' || r.status === 'IN_PROGRESS' || r.status === 'IMPLEMENTING') || runs[0] || null;
  });
}
