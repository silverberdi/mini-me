import { Component, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router } from '@angular/router';
import { RefreshService } from '../../core/refresh.service';
import { ApiService } from '../../core/api.service';

@Component({
  selector: 'app-proyectos',
  standalone: true,
  imports: [CommonModule, RouterModule],
  template: `
    <div class="space-y-6">
      <!-- Header -->
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-slate-800/40 p-6 rounded-2xl border border-slate-700/50 backdrop-blur-sm">
        <div>
          <h1 class="text-2xl font-bold tracking-tight text-white">Proyectos Administrados</h1>
          <p class="text-sm text-slate-400 mt-1">Configuración, vinculaciones y estado administrativo de repositorios bajo la autoridad mini me.</p>
        </div>
      </div>

      <!-- Action Feedback Banner -->
      <div *ngIf="actionMsg()"
           class="p-4 rounded-xl text-xs font-mono flex items-center justify-between"
           [ngClass]="actionOk() ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'">
        <span>{{ actionMsg() }}</span>
        <button (click)="actionMsg.set(null)" class="text-slate-400 hover:text-white ml-2">✕</button>
      </div>

      <!-- Projects Grid -->
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <div *ngFor="let proj of refresh.projects()"
             (click)="selectProject(proj.project_id)"
             class="group cursor-pointer p-6 rounded-2xl bg-slate-800/40 border transition-all duration-200 flex flex-col justify-between"
             [ngClass]="refresh.activeProject()?.project_id === proj.project_id ? 'border-sky-500 bg-slate-800/80 shadow-lg shadow-sky-500/10' : 'border-slate-700/50 hover:border-slate-600 hover:bg-slate-800/60'">
          <div>
            <div class="flex items-center justify-between">
              <h2 class="text-lg font-bold text-white group-hover:text-sky-400 transition-colors">{{ proj.project_id }}</h2>
              <span class="px-2.5 py-0.5 text-xs font-semibold rounded-full uppercase font-mono"
                    [ngClass]="proj.status === 'ACTIVE' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'">
                {{ proj.status || 'ACTIVE' }}
              </span>
            </div>

            <p class="text-xs text-slate-400 font-mono mt-3 truncate">{{ proj.repo_path || proj.repository || 'Ruta local no especificada' }}</p>

            <div class="mt-4 pt-4 border-t border-slate-700/50 space-y-2 text-xs text-slate-400">
              <div class="flex items-center justify-between">
                <span>GitHub:</span>
                <span class="font-mono text-slate-300 truncate max-w-[180px]">{{ proj.repository || proj.github_repo || 'No vinculado' }}</span>
              </div>
              <div class="flex items-center justify-between">
                <span>Rama Base:</span>
                <span class="font-mono text-slate-300">{{ proj.base_branch || 'main' }}</span>
              </div>
            </div>
          </div>

          <div class="mt-4 pt-4 border-t border-slate-700/50 flex items-center justify-between">
            <span *ngIf="refresh.activeProject()?.project_id === proj.project_id" class="text-xs font-semibold text-sky-400 flex items-center gap-1.5">
              <span class="w-2 h-2 rounded-full bg-sky-400 animate-pulse"></span> Proyecto en Foco
            </span>
            <span *ngIf="refresh.activeProject()?.project_id !== proj.project_id" class="text-xs text-slate-500 group-hover:text-slate-300">
              Clic para enfocar
            </span>
          </div>
        </div>

        <div *ngIf="refresh.projects().length === 0" class="col-span-full text-center py-16 text-slate-500 text-sm bg-slate-800/20 rounded-2xl border border-slate-800">
          No hay proyectos registrados en la autoridad duradera.
        </div>
      </div>

      <!-- Active Project Detail Panel -->
      <div *ngIf="refresh.activeProject()" class="bg-slate-800/40 rounded-2xl border border-slate-700/50 p-6 backdrop-blur-sm space-y-6 shadow-xl">
        <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-700/60 pb-4">
          <div>
            <h3 class="text-lg font-bold text-white flex items-center gap-3">
              <span>Gestión de Proyecto: {{ refresh.activeProject().project_id }}</span>
              <span class="px-2.5 py-0.5 text-xs font-semibold rounded-full uppercase font-mono"
                    [ngClass]="refresh.activeProject().status === 'ACTIVE' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'">
                {{ refresh.activeProject().status || 'ACTIVE' }}
              </span>
            </h3>
            <p class="text-xs text-slate-400 mt-1">Acciones de ciclo de vida y navegación contextual para el proyecto activo.</p>
          </div>

          <!-- Project Actions Toolbar -->
          <div class="flex items-center gap-2 flex-wrap">
            <button
              (click)="toggleProjectPause()"
              [disabled]="isActionRunning()"
              class="px-3.5 py-2 rounded-xl text-xs font-semibold border transition-all cursor-pointer"
              [ngClass]="refresh.activeProject().status === 'PAUSED' ? 'bg-emerald-600 hover:bg-emerald-500 text-white border-emerald-500/30' : 'bg-amber-600/20 hover:bg-amber-600/30 text-amber-300 border-amber-500/30'">
              {{ refresh.activeProject().status === 'PAUSED' ? '▶ Reanudar Proyecto' : '⏸ Pausar Proyecto' }}
            </button>

            <button
              (click)="verifyConnections()"
              [disabled]="isActionRunning()"
              class="px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-semibold transition-all cursor-pointer">
              Verificar Conexiones
            </button>

            <button
              (click)="openBacklog()"
              class="px-3.5 py-2 rounded-xl bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold shadow-md transition-all cursor-pointer">
              Abrir Backlog &rarr;
            </button>
          </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-6 text-xs font-mono">
          <div class="space-y-3 bg-slate-900/60 p-4 rounded-xl border border-slate-800">
            <div class="text-slate-300 font-bold uppercase font-sans mb-2">Identidad & Repositorio</div>
            <div class="flex justify-between py-1.5 border-b border-slate-800">
              <span class="text-slate-400 font-sans">Identificador:</span>
              <span class="text-white">{{ refresh.activeProject().project_id }}</span>
            </div>
            <div class="flex justify-between py-1.5 border-b border-slate-800">
              <span class="text-slate-400 font-sans">Repositorio GitHub:</span>
              <span class="text-slate-200">{{ refresh.activeProject().repository || refresh.activeProject().github_repo || 'No vinculado' }}</span>
            </div>
            <div class="flex justify-between py-1.5 border-b border-slate-800">
              <span class="text-slate-400 font-sans">Ruta en Host:</span>
              <span class="text-slate-200 truncate max-w-[220px]">{{ refresh.activeProject().repo_path || refresh.activeProject().local_path || 'No definida' }}</span>
            </div>
          </div>

          <div class="space-y-3 bg-slate-900/60 p-4 rounded-xl border border-slate-800">
            <div class="text-slate-300 font-bold uppercase font-sans mb-2">Políticas de Ejecución & Auditoría</div>
            <div class="flex justify-between py-1.5 border-b border-slate-800">
              <span class="text-slate-400 font-sans">Auditoría Independiente:</span>
              <span class="text-emerald-400 font-bold">REQUERIDA</span>
            </div>
            <div class="flex justify-between py-1.5 border-b border-slate-800">
              <span class="text-slate-400 font-sans">Verificación Estricta:</span>
              <span class="text-emerald-400 font-bold">FAIL-CLOSED</span>
            </div>
            <div class="flex justify-between py-1.5 border-b border-slate-800">
              <span class="text-slate-400 font-sans">Drain OpenRouter:</span>
              <span class="text-slate-300">SOLO EN AGOTAMIENTO</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  `
})
export class ProyectosComponent {
  private router = inject(Router);
  private api = inject(ApiService);
  public refresh = inject(RefreshService);

  readonly isActionRunning = signal<boolean>(false);
  readonly actionMsg = signal<string | null>(null);
  readonly actionOk = signal<boolean>(false);

  selectProject(projectId: string) {
    this.refresh.setSelectedProject(projectId);
  }

  openBacklog() {
    void this.router.navigate(['/backlog']);
  }

  async toggleProjectPause() {
    const proj = this.refresh.activeProject();
    if (!proj) return;

    this.isActionRunning.set(true);
    this.actionMsg.set(null);

    const isCurrentlyPaused = proj.status === 'PAUSED';
    const endpoint = isCurrentlyPaused
      ? `/api/v1/projects/${encodeURIComponent(proj.project_id)}/resume`
      : `/api/v1/projects/${encodeURIComponent(proj.project_id)}/pause`;

    try {
      const res = await this.api.post(endpoint, {});
      if (res.ok) {
        this.actionOk.set(true);
        this.actionMsg.set(isCurrentlyPaused ? `Proyecto ${proj.project_id} reanudado.` : `Proyecto ${proj.project_id} pausado.`);
        await this.refresh.read();
      } else {
        this.actionOk.set(false);
        this.actionMsg.set(`Error: ${res.error || 'No se pudo cambiar el estado del proyecto'}`);
      }
    } catch (e: any) {
      this.actionOk.set(false);
      this.actionMsg.set(`Error de conexión: ${e.message || e}`);
    } finally {
      this.isActionRunning.set(false);
    }
  }

  async verifyConnections() {
    const proj = this.refresh.activeProject();
    if (!proj) return;

    this.isActionRunning.set(true);
    this.actionMsg.set(null);

    try {
      const res = await this.api.post(`/api/v1/projects/${encodeURIComponent(proj.project_id)}/connections/verify`, {});
      if (res.ok) {
        this.actionOk.set(true);
        this.actionMsg.set(`Conexiones verificadas correctamente para ${proj.project_id}.`);
      } else {
        this.actionOk.set(false);
        this.actionMsg.set(`Fallo en verificación: ${res.error || 'Error'}`);
      }
    } catch (e: any) {
      this.actionOk.set(false);
      this.actionMsg.set(`Error de conexión: ${e.message || e}`);
    } finally {
      this.isActionRunning.set(false);
    }
  }
}
