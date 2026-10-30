import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RefreshService } from '../../core/refresh.service';

@Component({
  selector: 'app-trabajo',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="space-y-6">
      <div class="bg-slate-800/40 p-6 rounded-2xl border border-slate-700/50 backdrop-blur-sm">
        <h1 class="text-2xl font-bold tracking-tight text-white">Cola de Trabajo</h1>
        <p class="text-sm text-slate-400 mt-1">Gestión de runs activos, stages y asignaciones de ejecución para mini me.</p>
      </div>

      <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 overflow-hidden backdrop-blur-sm">
        <div class="p-4 border-b border-slate-700/60 flex items-center justify-between">
          <h2 class="text-base font-semibold text-white">Historial de Ejecuciones</h2>
          <span class="text-xs font-mono text-slate-400">{{ refresh.runs().length }} total</span>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-left text-sm text-slate-300">
            <thead class="bg-slate-900/60 text-xs uppercase font-semibold text-slate-400 border-b border-slate-700/60">
              <tr>
                <th class="px-6 py-3.5">Run ID</th>
                <th class="px-6 py-3.5">Proyecto</th>
                <th class="px-6 py-3.5">Cambio OpenSpec</th>
                <th class="px-6 py-3.5">Stage</th>
                <th class="px-6 py-3.5">Estado</th>
                <th class="px-6 py-3.5">Actualizado</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800/60">
              <tr *ngFor="let run of refresh.runs()" class="hover:bg-slate-800/30 transition-colors">
                <td class="px-6 py-4 font-mono text-xs text-sky-400 font-semibold">{{ run.run_id }}</td>
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
                          'bg-amber-500/10 text-amber-400 border border-amber-500/20': run.status === 'PAUSED' || run.status === 'WAITING'
                        }">
                    {{ run.status }}
                  </span>
                </td>
                <td class="px-6 py-4 text-xs text-slate-500 font-mono">{{ run.updated_at || 'Reciente' }}</td>
              </tr>
              <tr *ngIf="refresh.runs().length === 0">
                <td colspan="6" class="px-6 py-8 text-center text-slate-500 text-sm">
                  No se encontraron ejecuciones registradas.
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
  constructor(public refresh: RefreshService) {}
}
