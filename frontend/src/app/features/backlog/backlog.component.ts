import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RefreshService } from '../../core/refresh.service';

@Component({
  selector: 'app-backlog',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="space-y-6">
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-slate-800/40 p-6 rounded-2xl border border-slate-700/50 backdrop-blur-sm">
        <div>
          <h1 class="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
            <span>Backlog de Solicitudes</span>
            <span *ngIf="refresh.activeProject()" class="text-sm font-semibold px-2.5 py-0.5 rounded-full bg-sky-500/10 text-sky-400 border border-sky-500/20">
              {{ refresh.activeProject().project_id }}
            </span>
          </h1>
          <p class="text-sm text-slate-400 mt-1">Solicitudes sincronizadas desde GitHub Issues elegibles para ejecución autónoma.</p>
        </div>
      </div>

      <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 overflow-hidden backdrop-blur-sm">
        <div class="p-4 border-b border-slate-700/60 flex items-center justify-between">
          <h2 class="text-base font-semibold text-white">Solicitudes de Cambio</h2>
          <span class="text-xs font-mono text-slate-400">{{ refresh.requests().length }} en total</span>
        </div>

        <div class="divide-y divide-slate-800/60">
          <div *ngFor="let req of refresh.requests()" class="p-5 hover:bg-slate-800/30 transition-colors flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div class="min-w-0 pr-4">
              <div class="flex items-center gap-2.5">
                <span *ngIf="req.issue_number" class="text-sm font-mono font-bold text-sky-400">#{{ req.issue_number }}</span>
                <h3 class="text-base font-semibold text-white truncate">{{ req.title }}</h3>
              </div>
              <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-400 mt-2 font-mono">
                <span>ID: {{ req.request_id }}</span>
                <span>Actualizado: {{ req.updated_at || req.created_at || 'Reciente' }}</span>
              </div>
            </div>

            <div class="flex items-center gap-3 self-end md:self-center">
              <span class="px-2.5 py-1 text-xs font-semibold rounded-lg bg-slate-800 border border-slate-700 text-slate-300">
                {{ req.status }}
              </span>
            </div>
          </div>

          <div *ngIf="refresh.requests().length === 0" class="text-center py-12 text-slate-500 text-sm">
            No hay solicitudes disponibles en el backlog de este proyecto.
          </div>
        </div>
      </div>
    </div>
  `
})
export class BacklogComponent {
  constructor(public refresh: RefreshService) {}
}
