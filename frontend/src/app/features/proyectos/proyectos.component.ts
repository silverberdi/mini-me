import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RefreshService } from '../../core/refresh.service';

@Component({
  selector: 'app-proyectos',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="space-y-6">
      <div class="bg-slate-800/40 p-6 rounded-2xl border border-slate-700/50 backdrop-blur-sm">
        <h1 class="text-2xl font-bold tracking-tight text-white">Proyectos</h1>
        <p class="text-sm text-slate-400 mt-1">Repositorios y proyectos registrados en la autoridad mini me.</p>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <div *ngFor="let proj of refresh.projects()"
             (click)="selectProject(proj.project_id)"
             class="group cursor-pointer p-6 rounded-2xl bg-slate-800/40 border transition-all duration-200"
             [ngClass]="refresh.activeProject().project_id === proj.project_id ? 'border-sky-500 bg-slate-800/80 shadow-lg shadow-sky-500/10' : 'border-slate-700/50 hover:border-slate-600 hover:bg-slate-800/60'">
          <div class="flex items-center justify-between">
            <h2 class="text-lg font-bold text-white group-hover:text-sky-400 transition-colors">{{ proj.project_id }}</h2>
            <span class="px-2.5 py-0.5 text-xs font-semibold rounded-full"
                  [ngClass]="proj.status === 'ACTIVE' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-slate-800 text-slate-400 border border-slate-700'">
              {{ proj.status || 'ACTIVE' }}
            </span>
          </div>

          <p class="text-xs text-slate-400 font-mono mt-3 truncate">{{ proj.repo_path || 'Ruta local no especificada' }}</p>

          <div class="mt-4 pt-4 border-t border-slate-700/50 flex items-center justify-between text-xs text-slate-400">
            <span>GitHub:</span>
            <span class="font-mono text-slate-300 truncate max-w-[160px]">{{ proj.github_repo || 'No vinculado' }}</span>
          </div>

          <div class="mt-3 flex items-center justify-between">
            <span *ngIf="refresh.activeProject().project_id === proj.project_id" class="text-xs font-semibold text-sky-400 flex items-center gap-1">
              <span class="w-1.5 h-1.5 rounded-full bg-sky-400"></span> Proyecto Activo
            </span>
            <span *ngIf="refresh.activeProject().project_id !== proj.project_id" class="text-xs text-slate-500 group-hover:text-slate-400">
              Clic para seleccionar
            </span>
          </div>
        </div>

        <div *ngIf="refresh.projects().length === 0" class="col-span-full text-center py-12 text-slate-500 text-sm bg-slate-800/20 rounded-2xl border border-slate-800">
          No hay proyectos registrados en el repositorio central.
        </div>
      </div>
    </div>
  `
})
export class ProyectosComponent {
  constructor(public refresh: RefreshService) {}

  selectProject(projectId: string) {
    this.refresh.setSelectedProject(projectId);
  }
}
