import { Component, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RefreshService } from '../../core/refresh.service';
import { ApiService } from '../../core/api.service';
import { RequestItem } from '../../core/models';

@Component({
  selector: 'app-backlog',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="space-y-6">
      <!-- Header -->
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-slate-800/40 p-6 rounded-2xl border border-slate-700/50 backdrop-blur-sm">
        <div>
          <h1 class="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
            <span>Backlog de Solicitudes</span>
            <span *ngIf="refresh.activeProject()" class="text-sm font-semibold px-2.5 py-0.5 rounded-full bg-sky-500/10 text-sky-400 border border-sky-500/20">
              {{ refresh.activeProject().project_id }}
            </span>
          </h1>
          <p class="text-sm text-slate-400 mt-1">Gestión y observabilidad de solicitudes remotas sincronizadas desde GitHub Issues.</p>
        </div>

        <div class="flex items-center gap-3">
          <button
            (click)="showCreateModal.set(!showCreateModal())"
            class="px-4 py-2 rounded-xl bg-sky-600 hover:bg-sky-500 text-white font-semibold text-xs tracking-wide shadow-md transition-all flex items-center gap-1.5 cursor-pointer">
            <span>{{ showCreateModal() ? '✕ Cancelar' : '+ Nueva Solicitud' }}</span>
          </button>
        </div>
      </div>

      <!-- Create Request Modal / Form -->
      <div *ngIf="showCreateModal()" class="p-6 rounded-2xl bg-slate-900 border border-sky-500/40 shadow-2xl space-y-4">
        <div class="flex items-center justify-between border-b border-slate-800 pb-3">
          <h3 class="text-base font-bold text-white">Crear Nueva Solicitud de Cambio</h3>
          <span class="text-xs text-slate-400 font-mono">Proyecto: {{ refresh.activeProject().project_id }}</span>
        </div>

        <form (submit)="createRequest($event)" class="space-y-4">
          <div>
            <label for="reqTitle" class="block text-xs font-semibold text-slate-300 mb-1">Título de la Solicitud *</label>
            <input
              id="reqTitle"
              type="text"
              [(ngModel)]="newTitle"
              name="title"
              required
              placeholder="Ej: feat(ui): agregar soporte para notificaciones web push"
              class="w-full bg-slate-950 border border-slate-700 rounded-xl px-3.5 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-sky-500" />
          </div>

          <div>
            <label for="reqDesc" class="block text-xs font-semibold text-slate-300 mb-1">Descripción / Propósito *</label>
            <textarea
              id="reqDesc"
              rows="3"
              [(ngModel)]="newDescription"
              name="description"
              required
              placeholder="Detalla la necesidad de negocio o técnica..."
              class="w-full bg-slate-950 border border-slate-700 rounded-xl p-3 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"></textarea>
          </div>

          <div>
            <label for="reqCriteria" class="block text-xs font-semibold text-slate-300 mb-1">Criterios de Aceptación (Gherkin o texto) *</label>
            <textarea
              id="reqCriteria"
              rows="3"
              [(ngModel)]="newCriteria"
              name="criteria"
              required
              placeholder="Given ... When ... Then ..."
              class="w-full bg-slate-950 border border-slate-700 rounded-xl p-3 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"></textarea>
          </div>

          <div class="flex items-center justify-between pt-2">
            <span *ngIf="actionMessage()" class="text-xs font-mono" [ngClass]="actionSuccess() ? 'text-emerald-400' : 'text-rose-400'">
              {{ actionMessage() }}
            </span>
            <div class="flex items-center gap-2 ml-auto">
              <button
                type="button"
                (click)="showCreateModal.set(false)"
                class="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold">
                Cancelar
              </button>
              <button
                type="submit"
                [disabled]="isSubmitting() || !newTitle.trim() || !newDescription.trim() || !newCriteria.trim()"
                class="px-5 py-2 rounded-xl bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white font-semibold text-xs tracking-wide shadow-md">
                {{ isSubmitting() ? 'Creando…' : 'Crear Solicitud en GitHub' }}
              </button>
            </div>
          </div>
        </form>
      </div>

      <!-- Action Feedback Banner -->
      <div *ngIf="actionMessage() && !showCreateModal()"
           class="p-4 rounded-xl text-xs font-mono flex items-center justify-between"
           [ngClass]="actionSuccess() ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'">
        <span>{{ actionMessage() }}</span>
        <button (click)="actionMessage.set(null)" class="text-slate-400 hover:text-white ml-2">✕</button>
      </div>

      <!-- Tabs (Pendientes vs Terminados) -->
      <div class="flex items-center gap-2 border-b border-slate-800 pb-2">
        <button
          (click)="activeTab.set('pending')"
          [ngClass]="activeTab() === 'pending' ? 'bg-sky-500/10 text-sky-400 border-sky-500/30' : 'text-slate-400 hover:text-white border-transparent'"
          class="px-4 py-2 rounded-xl text-xs font-bold border transition-all flex items-center gap-2 cursor-pointer">
          <span>Solicitudes Pendientes</span>
          <span class="px-2 py-0.5 rounded-full text-[11px] font-mono"
                [ngClass]="activeTab() === 'pending' ? 'bg-sky-500 text-white' : 'bg-slate-800 text-slate-400'">
            {{ refresh.requests().length }}
          </span>
        </button>

        <button
          (click)="activeTab.set('closed')"
          [ngClass]="activeTab() === 'closed' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' : 'text-slate-400 hover:text-white border-transparent'"
          class="px-4 py-2 rounded-xl text-xs font-bold border transition-all flex items-center gap-2 cursor-pointer">
          <span>Terminadas / Cerradas</span>
          <span class="px-2 py-0.5 rounded-full text-[11px] font-mono"
                [ngClass]="activeTab() === 'closed' ? 'bg-emerald-500 text-white' : 'bg-slate-800 text-slate-400'">
            {{ refresh.closedRequests().length }}
          </span>
        </button>
      </div>

      <!-- Content Area -->
      <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 overflow-hidden backdrop-blur-sm shadow-xl">
        <!-- PENDING REQUESTS TAB -->
        <div *ngIf="activeTab() === 'pending'" class="divide-y divide-slate-800/60">
          <div *ngFor="let req of refresh.requests()" class="p-5 hover:bg-slate-800/30 transition-colors flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div class="min-w-0 pr-4">
              <div class="flex items-center gap-2.5 flex-wrap">
                <span *ngIf="req.issue_number" class="text-sm font-mono font-bold text-sky-400">#{{ req.issue_number }}</span>
                <h3 class="text-base font-semibold text-white">{{ req.title }}</h3>
                <span class="px-2 py-0.5 text-[11px] font-semibold rounded-md uppercase font-mono"
                      [ngClass]="req.status === 'ELIGIBLE' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-slate-800 text-slate-400 border border-slate-700'">
                  {{ req.status }}
                </span>
              </div>
              <p *ngIf="req.body" class="text-xs text-slate-400 mt-1 line-clamp-2">{{ req.body }}</p>
              <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 mt-2 font-mono">
                <span>ID: {{ req.request_id }}</span>
                <span>Actualizado: {{ req.updated_at || req.created_at || 'Reciente' }}</span>
              </div>
            </div>

            <!-- Actions Per Request -->
            <div class="flex items-center gap-2 shrink-0 self-end md:self-center">
              <button
                *ngIf="req.issue_number && req.status === 'ELIGIBLE'"
                (click)="runRequest(req.issue_number)"
                [disabled]="isSubmitting()"
                class="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white font-semibold text-xs transition-colors cursor-pointer flex items-center gap-1">
                <span>▶ Iniciar Run</span>
              </button>

              <button
                *ngIf="req.issue_number && req.status !== 'PAUSED'"
                (click)="deactivateRequest(req.issue_number)"
                [disabled]="isSubmitting()"
                class="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 text-xs font-semibold transition-colors cursor-pointer"
                title="Pausar elegibilidad de este ticket">
                Pausar
              </button>

              <button
                *ngIf="req.issue_number && req.status === 'PAUSED'"
                (click)="reactivateRequest(req.issue_number)"
                [disabled]="isSubmitting()"
                class="px-3 py-1.5 rounded-lg bg-sky-600/20 hover:bg-sky-600/30 border border-sky-500/30 text-sky-300 text-xs font-semibold transition-colors cursor-pointer"
                title="Reactivar elegibilidad en cola FIFO">
                Reactivar
              </button>
            </div>
          </div>

          <div *ngIf="refresh.requests().length === 0" class="text-center py-16 text-slate-500 text-sm space-y-1">
            <div class="text-2xl mb-1">📭</div>
            <div class="font-medium text-slate-400">No hay solicitudes pendientes en este proyecto</div>
            <p class="text-xs">Usa el botón "+ Nueva Solicitud" para registrar una nueva tarea en el repositorio.</p>
          </div>
        </div>

        <!-- CLOSED REQUESTS TAB -->
        <div *ngIf="activeTab() === 'closed'" class="divide-y divide-slate-800/60">
          <div *ngFor="let req of refresh.closedRequests()" class="p-5 hover:bg-slate-800/30 transition-colors flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div class="min-w-0 pr-4">
              <div class="flex items-center gap-2.5 flex-wrap">
                <span *ngIf="req.issue_number" class="text-sm font-mono font-bold text-slate-500">#{{ req.issue_number }}</span>
                <h3 class="text-base font-semibold text-slate-300 line-through">{{ req.title }}</h3>
                <span class="px-2 py-0.5 text-[11px] font-semibold rounded-md bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono">
                  COMPLETED / CLOSED
                </span>
              </div>
              <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 mt-2 font-mono">
                <span>ID: {{ req.request_id || req.issue_number }}</span>
                <span>Cerrado en repositorio remoto</span>
              </div>
            </div>
            <div>
              <span class="text-xs font-mono text-emerald-400 font-semibold">✓ Entregado</span>
            </div>
          </div>

          <div *ngIf="refresh.closedRequests().length === 0" class="text-center py-16 text-slate-500 text-sm space-y-1">
            <div class="text-2xl mb-1">🏁</div>
            <div class="font-medium text-slate-400">No hay solicitudes terminadas registradas</div>
            <p class="text-xs">Los issues cerrados tras los ciclos de entrega autónoma aparecerán aquí.</p>
          </div>
        </div>
      </div>
    </div>
  `
})
export class BacklogComponent {
  private api = inject(ApiService);
  public refresh = inject(RefreshService);

  readonly activeTab = signal<'pending' | 'closed'>('pending');
  readonly showCreateModal = signal<boolean>(false);
  readonly isSubmitting = signal<boolean>(false);
  readonly actionMessage = signal<string | null>(null);
  readonly actionSuccess = signal<boolean>(false);

  newTitle = '';
  newDescription = '';
  newCriteria = '';

  async createRequest(event: Event): Promise<void> {
    event.preventDefault();
    const pid = this.refresh.activeProject()?.project_id;
    if (!pid || !this.newTitle.trim()) return;

    this.isSubmitting.set(true);
    this.actionMessage.set(null);

    try {
      const res = await this.api.post(`/api/v1/projects/${encodeURIComponent(pid)}/requests`, {
        title: this.newTitle.trim(),
        description: this.newDescription.trim(),
        acceptance_criteria: this.newCriteria.trim()
      });

      if (res.ok) {
        this.actionSuccess.set(true);
        this.actionMessage.set('Solicitud creada y sincronizada con éxito en el repositorio remoto.');
        this.newTitle = '';
        this.newDescription = '';
        this.newCriteria = '';
        this.showCreateModal.set(false);
        await this.refresh.read();
      } else {
        this.actionSuccess.set(false);
        this.actionMessage.set(`Error al crear solicitud: ${res.error || 'Error no especificado'}`);
      }
    } catch (e: any) {
      this.actionSuccess.set(false);
      this.actionMessage.set(`Error de conexión: ${e.message || e}`);
    } finally {
      this.isSubmitting.set(false);
    }
  }

  async runRequest(issueNumber: number): Promise<void> {
    const pid = this.refresh.activeProject()?.project_id;
    if (!pid) return;

    if (!confirm(`¿Iniciar ejecución autónoma para el Issue #${issueNumber}?`)) return;

    this.isSubmitting.set(true);
    try {
      const res = await this.api.post(`/api/v1/projects/${encodeURIComponent(pid)}/requests/run`, {
        issue_number: issueNumber
      });
      if (res.ok) {
        this.actionSuccess.set(true);
        this.actionMessage.set(`Ejecución admitida para el Issue #${issueNumber}. El orquestador iniciará el ciclo.`);
        await this.refresh.read();
      } else {
        this.actionSuccess.set(false);
        this.actionMessage.set(`No se pudo iniciar el run: ${res.error || 'Error no especificado'}`);
      }
    } catch (e: any) {
      this.actionSuccess.set(false);
      this.actionMessage.set(`Error de comunicación: ${e.message || e}`);
    } finally {
      this.isSubmitting.set(false);
    }
  }

  async deactivateRequest(issueNumber: number): Promise<void> {
    const pid = this.refresh.activeProject()?.project_id;
    if (!pid) return;

    this.isSubmitting.set(true);
    try {
      const res = await this.api.post(`/api/v1/projects/${encodeURIComponent(pid)}/requests/${issueNumber}/deactivate`, {});
      if (res.ok) {
        this.actionSuccess.set(true);
        this.actionMessage.set(`Solicitud #${issueNumber} pausada.`);
        await this.refresh.read();
      } else {
        this.actionSuccess.set(false);
        this.actionMessage.set(`Error al pausar: ${res.error || 'Error'}`);
      }
    } catch (e: any) {
      this.actionSuccess.set(false);
      this.actionMessage.set(`Error: ${e.message || e}`);
    } finally {
      this.isSubmitting.set(false);
    }
  }

  async reactivateRequest(issueNumber: number): Promise<void> {
    const pid = this.refresh.activeProject()?.project_id;
    if (!pid) return;

    this.isSubmitting.set(true);
    try {
      const res = await this.api.post(`/api/v1/projects/${encodeURIComponent(pid)}/requests/${issueNumber}/reactivate`, {});
      if (res.ok) {
        this.actionSuccess.set(true);
        this.actionMessage.set(`Solicitud #${issueNumber} reactivada en la cola.`);
        await this.refresh.read();
      } else {
        this.actionSuccess.set(false);
        this.actionMessage.set(`Error al reactivar: ${res.error || 'Error'}`);
      }
    } catch (e: any) {
      this.actionSuccess.set(false);
      this.actionMessage.set(`Error: ${e.message || e}`);
    } finally {
      this.isSubmitting.set(false);
    }
  }
}
