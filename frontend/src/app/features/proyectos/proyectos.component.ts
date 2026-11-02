import { Component, signal, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule, Router } from '@angular/router';
import { RefreshService } from '../../core/refresh.service';
import { ApiService } from '../../core/api.service';
import { ProjectAgentProfile, ProjectExecutionPolicy } from '../../core/models';

@Component({
  selector: 'app-proyectos',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  template: `
    <div class="space-y-6">
      <!-- Header -->
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-slate-800/40 p-6 rounded-2xl border border-slate-700/50 backdrop-blur-sm">
        <div>
          <h1 class="text-2xl font-bold tracking-tight text-white">Proyectos Administrados</h1>
          <p class="text-sm text-slate-400 mt-1">Configuración, vinculaciones y estado administrativo de repositorios bajo la autoridad mini me.</p>
        </div>
        <div class="flex items-center gap-3">
          <button (click)="openCreateModal()"
                  class="px-4 py-2.5 rounded-xl bg-sky-500 hover:bg-sky-400 text-slate-950 font-bold text-xs tracking-wide shadow-lg shadow-sky-500/20 transition-all flex items-center gap-2 cursor-pointer">
            <span>+</span>
            <span>Nuevo Proyecto</span>
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

      <!-- Projects Grid -->
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <div *ngFor="let proj of refresh.projects()"
             (click)="selectProject(proj.project_id)"
             class="group cursor-pointer p-6 rounded-2xl bg-slate-800/40 border transition-all duration-200 flex flex-col justify-between"
             [ngClass]="refresh.activeProject()?.project_id === proj.project_id ? 'border-sky-500 bg-slate-800/80 shadow-lg shadow-sky-500/10' : 'border-slate-700/50 hover:border-slate-600 hover:bg-slate-800/60'">
          <div>
            <div class="flex items-center justify-between">
              <h2 class="text-lg font-bold text-white group-hover:text-sky-400 transition-colors">{{ proj.display_name || proj.project_id }}</h2>
              <span class="px-2.5 py-0.5 text-xs font-semibold rounded-full uppercase font-mono"
                    [ngClass]="proj.status === 'ACTIVE' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'">
                {{ proj.status || 'ACTIVE' }}
              </span>
            </div>

            <p class="text-xs text-slate-400 font-mono mt-1 text-[11px]">ID: {{ proj.project_id }}</p>
            <p class="text-xs text-slate-400 font-mono mt-2 truncate">{{ proj.repo_path || proj.repository || 'Ruta local no especificada' }}</p>

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
              <span>Gestión: {{ refresh.activeProject().display_name || refresh.activeProject().project_id }}</span>
              <span class="px-2.5 py-0.5 text-xs font-semibold rounded-full uppercase font-mono"
                    [ngClass]="refresh.activeProject().status === 'ACTIVE' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'">
                {{ refresh.activeProject().status || 'ACTIVE' }}
              </span>
            </h3>
            <p class="text-xs text-slate-400 mt-1">Configuración técnica, perfiles de agentes y modelos asignados por etapa.</p>
          </div>

          <!-- Project Actions Toolbar -->
          <div class="flex items-center gap-2 flex-wrap">
            <button
              (click)="openEditModal()"
              class="px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-sky-400 text-xs font-semibold transition-all cursor-pointer flex items-center gap-1.5">
              <span>✏️</span>
              <span>Editar Modelos & Ajustes</span>
            </button>

            <button
              (click)="toggleProjectPause()"
              [disabled]="isActionRunning()"
              class="px-3.5 py-2 rounded-xl text-xs font-semibold border transition-all cursor-pointer"
              [ngClass]="refresh.activeProject().status === 'PAUSED' ? 'bg-emerald-600 hover:bg-emerald-500 text-white border-emerald-500/30' : 'bg-amber-600/20 hover:bg-amber-600/30 text-amber-300 border-amber-500/30'">
              {{ refresh.activeProject().status === 'PAUSED' ? '▶ Reanudar' : '⏸ Pausar' }}
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

        <!-- Details Grid -->
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
              <span class="text-slate-400 font-sans">Rama Base:</span>
              <span class="text-slate-200">{{ refresh.activeProject().base_branch || 'main' }}</span>
            </div>
            <div class="flex justify-between py-1.5 border-b border-slate-800">
              <span class="text-slate-400 font-sans">Ruta en Host:</span>
              <span class="text-slate-200 truncate max-w-[220px]">{{ refresh.activeProject().repo_path || refresh.activeProject().local_path || 'No definida' }}</span>
            </div>
          </div>

          <div class="space-y-3 bg-slate-900/60 p-4 rounded-xl border border-slate-800">
            <div class="text-slate-300 font-bold uppercase font-sans mb-2">Asignación de Modelos por Rol / Etapa</div>
            <div class="flex justify-between py-1.5 border-b border-slate-800">
              <span class="text-slate-400 font-sans">Thinking (Exploración / Propuesta):</span>
              <span class="text-sky-300 font-bold">{{ getRoleModel('thinking') }}</span>
            </div>
            <div class="flex justify-between py-1.5 border-b border-slate-800">
              <span class="text-slate-400 font-sans">Execution (Implementación):</span>
              <span class="text-emerald-300 font-bold">{{ getRoleModel('execution') }}</span>
            </div>
            <div class="flex justify-between py-1.5 border-b border-slate-800">
              <span class="text-slate-400 font-sans">Independent Review (Revisión):</span>
              <span class="text-amber-300 font-bold">{{ getRoleModel('independent_review') }}</span>
            </div>
            <div class="flex justify-between py-1.5 border-b border-slate-800">
              <span class="text-slate-400 font-sans">Fallback (Agotamiento):</span>
              <span class="text-purple-300 font-bold">{{ getRoleModel('fallback') }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Modal: Crear Proyecto -->
    <div *ngIf="showCreateModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fade-in">
      <div class="bg-slate-900 border border-slate-800 rounded-2xl max-w-lg w-full p-6 shadow-2xl relative space-y-4 max-h-[90vh] overflow-y-auto">
        <button (click)="showCreateModal = false" class="absolute top-4 right-4 text-slate-400 hover:text-white text-lg">✕</button>

        <div>
          <h2 class="text-lg font-bold text-white">Registrar Nuevo Proyecto</h2>
          <p class="text-xs text-slate-400 mt-0.5">Ingresa los datos para registrar un repositorio bajo la autoridad de mini me.</p>
        </div>

        <form (ngSubmit)="submitCreateProject()" class="space-y-4 text-xs">
          <div>
            <label class="block text-slate-300 font-medium mb-1">ID del Proyecto (slug único)</label>
            <input type="text" [(ngModel)]="newProject.project_id" name="project_id" required
                   placeholder="ej. mini-me, my-service"
                   class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-white focus:outline-none focus:border-sky-500 font-mono">
          </div>

          <div>
            <label class="block text-slate-300 font-medium mb-1">Nombre Descriptivo</label>
            <input type="text" [(ngModel)]="newProject.display_name" name="display_name" required
                   placeholder="ej. Mini Me Core"
                   class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-white focus:outline-none focus:border-sky-500">
          </div>

          <div>
            <label class="block text-slate-300 font-medium mb-1">Repositorio GitHub (owner/repo)</label>
            <input type="text" [(ngModel)]="newProject.repository" name="repository" required
                   placeholder="ej. silverberdi/mini-me"
                   class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-white focus:outline-none focus:border-sky-500 font-mono">
          </div>

          <div>
            <label class="block text-slate-300 font-medium mb-1">Rama Base</label>
            <input type="text" [(ngModel)]="newProject.base_branch" name="base_branch" required
                   placeholder="main"
                   class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-white focus:outline-none focus:border-sky-500 font-mono">
          </div>

          <div class="pt-3 border-t border-slate-800 space-y-3">
            <h3 class="font-bold text-slate-200">Modelos Asignados por Etapa</h3>

            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="block text-slate-400 mb-1">Thinking (Exploración)</label>
                <select [(ngModel)]="newProjectProfiles.thinking" name="model_thinking"
                        class="w-full bg-slate-800 border border-slate-700 rounded-xl px-2.5 py-2 text-white focus:outline-none focus:border-sky-500 font-mono text-[11px]">
                  <optgroup *ngFor="let g of modelGroups" [label]="g.name">
                    <option *ngFor="let m of g.models" [value]="m.id">{{ m.label }}</option>
                  </optgroup>
                </select>
              </div>

              <div>
                <label class="block text-slate-400 mb-1">Execution (Código)</label>
                <select [(ngModel)]="newProjectProfiles.execution" name="model_execution"
                        class="w-full bg-slate-800 border border-slate-700 rounded-xl px-2.5 py-2 text-white focus:outline-none focus:border-sky-500 font-mono text-[11px]">
                  <optgroup *ngFor="let g of modelGroups" [label]="g.name">
                    <option *ngFor="let m of g.models" [value]="m.id">{{ m.label }}</option>
                  </optgroup>
                </select>
              </div>

              <div>
                <label class="block text-slate-400 mb-1">Review (Revisión)</label>
                <select [(ngModel)]="newProjectProfiles.independent_review" name="model_review"
                        class="w-full bg-slate-800 border border-slate-700 rounded-xl px-2.5 py-2 text-white focus:outline-none focus:border-sky-500 font-mono text-[11px]">
                  <optgroup *ngFor="let g of modelGroups" [label]="g.name">
                    <option *ngFor="let m of g.models" [value]="m.id">{{ m.label }}</option>
                  </optgroup>
                </select>
              </div>

              <div>
                <label class="block text-slate-400 mb-1">Fallback (Respaldo)</label>
                <select [(ngModel)]="newProjectProfiles.fallback" name="model_fallback"
                        class="w-full bg-slate-800 border border-slate-700 rounded-xl px-2.5 py-2 text-white focus:outline-none focus:border-sky-500 font-mono text-[11px]">
                  <optgroup *ngFor="let g of modelGroups" [label]="g.name">
                    <option *ngFor="let m of g.models" [value]="m.id">{{ m.label }}</option>
                  </optgroup>
                </select>
              </div>
            </div>

            <!-- Independence warning -->
            <div *ngIf="isReviewerConflict(newProjectProfiles)"
                 class="p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-300 text-[11px]">
              ⚠️ <strong>Principio de Independencia:</strong> La revisión independiente debe ser de un proveedor distinto a la ejecución (ej. OpenCode o Codex ↔ Antigravity).
            </div>

            <!-- Architecture Info Banner -->
            <div class="p-2.5 rounded-xl bg-slate-800/60 border border-slate-700/50 text-slate-400 text-[11px] space-y-1">
              <div class="font-semibold text-slate-300 flex items-center gap-1.5">
                <span>ℹ️</span> <span>Modelos y Proveedores (Contrato Rector 1.3):</span>
              </div>
              <p>• <strong>OpenCode CLI</strong>: Ejecuta modelos API externos (<strong class="text-sky-300">opencode-deepseek (API)</strong> y <strong class="text-sky-300">opencode-deepseek (openrouter)</strong>).</p>
              <p>• <strong>Anthropic Claude & Google Gemini</strong>: Operan vía el harness <strong>Antigravity</strong> con capacidades OpenSpec.</p>
              <p>• <strong>OpenAI GPT</strong>: Opera vía el harness <strong>Codex</strong>.</p>
              <p>• <strong>DeepSeek Directo</strong>: Auditor de solo lectura (<code class="text-sky-300">CONTRACT_REVIEW</code> y <code class="text-sky-300">REVIEW</code>).</p>
            </div>
          </div>

          <div class="pt-4 flex items-center justify-end gap-3">
            <button type="button" (click)="showCreateModal = false"
                    class="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold cursor-pointer">
              Cancelar
            </button>
            <button type="submit" [disabled]="isActionRunning() || isReviewerConflict(newProjectProfiles)"
                    class="px-4 py-2 rounded-xl bg-sky-500 hover:bg-sky-400 disabled:opacity-50 text-slate-950 font-bold cursor-pointer">
              {{ isActionRunning() ? 'Guardando…' : 'Crear Proyecto' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Modal: Editar Proyecto & Asignación de Modelos -->
    <div *ngIf="showEditModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fade-in">
      <div class="bg-slate-900 border border-slate-800 rounded-2xl max-w-lg w-full p-6 shadow-2xl relative space-y-4 max-h-[90vh] overflow-y-auto">
        <button (click)="showEditModal = false" class="absolute top-4 right-4 text-slate-400 hover:text-white text-lg">✕</button>

        <div>
          <h2 class="text-lg font-bold text-white">Editar Proyecto: {{ editProject.project_id }}</h2>
          <p class="text-xs text-slate-400 mt-0.5">Modifica nombre, rama base y los modelos autónomos asignados por etapa.</p>
        </div>

        <form (ngSubmit)="submitEditProject()" class="space-y-4 text-xs">
          <div>
            <label class="block text-slate-300 font-medium mb-1">Nombre Descriptivo</label>
            <input type="text" [(ngModel)]="editProject.display_name" name="display_name" required
                   class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-white focus:outline-none focus:border-sky-500">
          </div>

          <div>
            <label class="block text-slate-300 font-medium mb-1">Rama Base</label>
            <input type="text" [(ngModel)]="editProject.base_branch" name="base_branch" required
                   class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-2 text-white focus:outline-none focus:border-sky-500 font-mono">
          </div>

          <div class="pt-3 border-t border-slate-800 space-y-3">
            <h3 class="font-bold text-slate-200">Asignación de Modelos por Etapa</h3>

            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="block text-slate-400 mb-1">Thinking (Exploración)</label>
                <select [(ngModel)]="editProjectProfiles.thinking" name="edit_thinking"
                        class="w-full bg-slate-800 border border-slate-700 rounded-xl px-2.5 py-2 text-white focus:outline-none focus:border-sky-500 font-mono text-[11px]">
                  <optgroup *ngFor="let g of modelGroups" [label]="g.name">
                    <option *ngFor="let m of g.models" [value]="m.id">{{ m.label }}</option>
                  </optgroup>
                </select>
              </div>

              <div>
                <label class="block text-slate-400 mb-1">Execution (Implementación)</label>
                <select [(ngModel)]="editProjectProfiles.execution" name="edit_execution"
                        class="w-full bg-slate-800 border border-slate-700 rounded-xl px-2.5 py-2 text-white focus:outline-none focus:border-sky-500 font-mono text-[11px]">
                  <optgroup *ngFor="let g of modelGroups" [label]="g.name">
                    <option *ngFor="let m of g.models" [value]="m.id">{{ m.label }}</option>
                  </optgroup>
                </select>
              </div>

              <div>
                <label class="block text-slate-400 mb-1">Review (Revisión Independiente)</label>
                <select [(ngModel)]="editProjectProfiles.independent_review" name="edit_review"
                        class="w-full bg-slate-800 border border-slate-700 rounded-xl px-2.5 py-2 text-white focus:outline-none focus:border-sky-500 font-mono text-[11px]">
                  <optgroup *ngFor="let g of modelGroups" [label]="g.name">
                    <option *ngFor="let m of g.models" [value]="m.id">{{ m.label }}</option>
                  </optgroup>
                </select>
              </div>

              <div>
                <label class="block text-slate-400 mb-1">Fallback (Agotamiento)</label>
                <select [(ngModel)]="editProjectProfiles.fallback" name="edit_fallback"
                        class="w-full bg-slate-800 border border-slate-700 rounded-xl px-2.5 py-2 text-white focus:outline-none focus:border-sky-500 font-mono text-[11px]">
                  <optgroup *ngFor="let g of modelGroups" [label]="g.name">
                    <option *ngFor="let m of g.models" [value]="m.id">{{ m.label }}</option>
                  </optgroup>
                </select>
              </div>
            </div>

            <!-- Independence warning -->
            <div *ngIf="isReviewerConflict(editProjectProfiles)"
                 class="p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-300 text-[11px]">
              ⚠️ <strong>Principio de Independencia:</strong> La revisión independiente debe ser de un proveedor distinto a la ejecución (ej. OpenCode o Codex ↔ Antigravity).
            </div>

            <!-- Architecture Info Banner -->
            <div class="p-2.5 rounded-xl bg-slate-800/60 border border-slate-700/50 text-slate-400 text-[11px] space-y-1">
              <div class="font-semibold text-slate-300 flex items-center gap-1.5">
                <span>ℹ️</span> <span>Modelos y Proveedores (Contrato Rector 1.3):</span>
              </div>
              <p>• <strong>OpenCode CLI</strong>: Ejecuta modelos API externos (<strong class="text-sky-300">opencode-deepseek (API)</strong> y <strong class="text-sky-300">opencode-deepseek (openrouter)</strong>).</p>
              <p>• <strong>Anthropic Claude & Google Gemini</strong>: Operan vía el harness <strong>Antigravity</strong> con capacidades OpenSpec.</p>
              <p>• <strong>OpenAI GPT</strong>: Opera vía el harness <strong>Codex</strong>.</p>
              <p>• <strong>DeepSeek Directo</strong>: Auditor de solo lectura (<code class="text-sky-300">CONTRACT_REVIEW</code> y <code class="text-sky-300">REVIEW</code>).</p>
            </div>
          </div>

          <div class="pt-4 flex items-center justify-end gap-3">
            <button type="button" (click)="showEditModal = false"
                    class="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold cursor-pointer">
              Cancelar
            </button>
            <button type="submit" [disabled]="isActionRunning() || isReviewerConflict(editProjectProfiles)"
                    class="px-4 py-2 rounded-xl bg-sky-500 hover:bg-sky-400 disabled:opacity-50 text-slate-950 font-bold cursor-pointer">
              {{ isActionRunning() ? 'Guardando…' : 'Guardar Cambios' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  `
})
export class ProyectosComponent implements OnInit {
  private router = inject(Router);
  private api = inject(ApiService);
  public refresh = inject(RefreshService);

  readonly isActionRunning = signal<boolean>(false);
  readonly actionMsg = signal<string | null>(null);
  readonly actionOk = signal<boolean>(false);

  showCreateModal = false;
  showEditModal = false;

  // Available models catalog for selection
  availableModels: {
    id: string;
    label: string;
    agent: string;
    effort: string;
    group: string;
  }[] = [
    // OpenCode CLI (Modelos API)
    { id: 'deepseek-chat', label: 'opencode-deepseek (API)', agent: 'opencode', effort: 'medium', group: 'OpenCode CLI (Modelos API)' },
    { id: 'deepseek/deepseek-chat', label: 'opencode-deepseek (OpenRouter)', agent: 'opencode', effort: 'medium', group: 'OpenCode CLI (Modelos API)' },
    { id: 'deepseek-reasoner', label: 'opencode-deepseek-r1 (API)', agent: 'opencode', effort: 'medium', group: 'OpenCode CLI (Modelos API)' },

    // Anthropic Claude via Antigravity
    { id: 'claude-sonnet-5-5-medium', label: 'Claude Sonnet 5.5 — Medio', agent: 'antigravity', effort: 'medium', group: 'Anthropic Claude (vía Antigravity)' },
    { id: 'claude-sonnet-5-5-high', label: 'Claude Sonnet 5.5 — Alto', agent: 'antigravity', effort: 'high', group: 'Anthropic Claude (vía Antigravity)' },
    { id: 'claude-opus-5-5-medium', label: 'Claude Opus 5.5 — Medio', agent: 'antigravity', effort: 'medium', group: 'Anthropic Claude (vía Antigravity)' },
    { id: 'claude-opus-5-5-high', label: 'Claude Opus 5.5 — Alto', agent: 'antigravity', effort: 'high', group: 'Anthropic Claude (vía Antigravity)' },

    // Google Gemini via Antigravity
    { id: 'gemini-3.8-flash-medium', label: 'Gemini 3.8 Flash — Medio', agent: 'antigravity', effort: 'medium', group: 'Google Gemini (vía Antigravity)' },
    { id: 'gemini-3.8-flash-high', label: 'Gemini 3.8 Flash — Alto', agent: 'antigravity', effort: 'high', group: 'Google Gemini (vía Antigravity)' },
    { id: 'gemini-4-argon-medium', label: 'Gemini 4 Argon — Medio', agent: 'antigravity', effort: 'medium', group: 'Google Gemini (vía Antigravity)' },
    { id: 'gemini-4-argon-high', label: 'Gemini 4 Argon — Alto', agent: 'antigravity', effort: 'high', group: 'Google Gemini (vía Antigravity)' },
    { id: 'gpt-oss-120b-medium', label: 'GPT-OSS 120B — Medio', agent: 'antigravity', effort: 'medium', group: 'Open Source (vía Antigravity)' },

    // OpenAI via Codex
    { id: 'gpt-5.6-luna', label: 'GPT-5.6 Luna — Medio', agent: 'codex', effort: 'medium', group: 'OpenAI GPT (vía Codex)' },
    { id: 'gpt-5.6-sol', label: 'GPT-5.6 Sol — Alto', agent: 'codex', effort: 'high', group: 'OpenAI GPT (vía Codex)' },
    { id: 'gpt-6.1-sol', label: 'GPT-6.1 Sol — Alto', agent: 'codex', effort: 'high', group: 'OpenAI GPT (vía Codex)' },
    { id: 'gpt-6-astra', label: 'GPT-6 Astra — Alto', agent: 'codex', effort: 'high', group: 'OpenAI GPT (vía Codex)' },
    { id: 'gpt-6.1-terra', label: 'GPT-6.1 Terra — Alto', agent: 'codex', effort: 'high', group: 'OpenAI GPT (vía Codex)' },
  ];

  newProject: any = {
    project_id: '',
    display_name: '',
    repository: '',
    base_branch: 'main',
  };

  newProjectProfiles = {
    thinking: 'gpt-5.6-luna',
    execution: 'gpt-5.6-luna',
    independent_review: 'claude-sonnet-5-5-medium',
    fallback: 'gpt-5.6-luna',
  };

  editProject: any = {
    project_id: '',
    display_name: '',
    base_branch: 'main',
  };

  editProjectProfiles = {
    thinking: 'gpt-5.6-luna',
    execution: 'gpt-5.6-luna',
    independent_review: 'claude-sonnet-5-5-medium',
    fallback: 'gpt-5.6-luna',
  };

  get modelGroups() {
    const groupsMap = new Map<string, typeof this.availableModels>();
    for (const m of this.availableModels) {
      if (!groupsMap.has(m.group)) {
        groupsMap.set(m.group, []);
      }
      groupsMap.get(m.group)!.push(m);
    }
    return Array.from(groupsMap.entries()).map(([name, models]) => ({ name, models }));
  }

  async ngOnInit(): Promise<void> {
    await this.loadAgentsCatalog();
  }

  async loadAgentsCatalog(): Promise<void> {
    try {
      const res = await this.api.get<any>('/api/v1/catalogs/agents');
      if (res.ok && res.data?.agents) {
        const parsed: typeof this.availableModels = [];
        for (const agent of res.data.agents) {
          const providerId = (agent.id || '').toLowerCase();
          const modelsObj = agent.models || {};
          for (const modelKey of Object.keys(modelsObj)) {
            const efforts: string[] = modelsObj[modelKey] || [];
            let group = 'Otros Modelos';
            let label = `${providerId} / ${modelKey}`;
            let effort = 'medium';

            if (modelKey.endsWith('-high') || (efforts.includes('high') && !efforts.includes('medium'))) {
              effort = 'high';
            } else if (modelKey.endsWith('-low')) {
              effort = 'low';
            } else if (efforts.includes('medium')) {
              effort = 'medium';
            } else if (efforts.length > 0) {
              effort = efforts[0];
            }

            if (providerId === 'opencode' || modelKey.includes('deepseek')) {
              group = 'OpenCode CLI (Modelos API)';
              if (modelKey.includes('/') || modelKey.includes('openrouter')) {
                label = 'opencode-deepseek (OpenRouter)';
              } else if (modelKey.includes('reasoner') || modelKey.includes('r1')) {
                label = 'opencode-deepseek-r1 (API)';
              } else {
                label = 'opencode-deepseek (API)';
              }
            } else if (modelKey.startsWith('claude')) {
              group = 'Anthropic Claude (vía Antigravity)';
              const sub = modelKey.replace('claude-', '').replace(/-[a-z]+$/, '');
              label = `Claude ${sub.replace('-', '.').toUpperCase()} — ${effort.toUpperCase()}`;
            } else if (modelKey.startsWith('gemini')) {
              group = 'Google Gemini (vía Antigravity)';
              const sub = modelKey.replace('gemini-', '').replace(/-[a-z]+$/, '');
              label = `Gemini ${sub.toUpperCase()} — ${effort.toUpperCase()}`;
            } else if (providerId === 'codex') {
              group = 'OpenAI GPT (vía Codex)';
              const sub = modelKey.replace('gpt-', '').toUpperCase();
              label = `GPT-${sub} — ${effort.toUpperCase()}`;
            } else if (modelKey.includes('oss')) {
              group = 'Open Source (vía Antigravity)';
              label = `GPT-OSS 120B — ${effort.toUpperCase()}`;
            }

            parsed.push({
              id: modelKey,
              label,
              agent: providerId,
              effort,
              group,
            });
          }
        }
        if (parsed.length > 0) {
          // Sort with Claude and Gemini first, then Codex
          this.availableModels = parsed.sort((a, b) => a.group.localeCompare(b.group) || a.label.localeCompare(b.label));
        }
      }
    } catch {
      // Keep sensible defaults
    }
  }

  isReviewerConflict(profiles: { thinking: string; execution: string; independent_review: string }): boolean {
    const execAgent = this.resolveAgentForModel(profiles.execution);
    const thinkAgent = this.resolveAgentForModel(profiles.thinking);
    const reviewAgent = this.resolveAgentForModel(profiles.independent_review);
    return reviewAgent === execAgent || reviewAgent === thinkAgent;
  }

  getRoleModel(role: string): string {
    const proj = this.refresh.activeProject();
    if (!proj || !proj.agent_profiles) return 'Configuración por defecto';
    const profile = proj.agent_profiles[role];
    if (!profile) return 'No asignado';
    const found = this.availableModels.find(m => m.id === profile.model_id);
    const effort = profile.effort ? ` [${profile.effort.slice(0, 3)}]` : '';
    if (found) {
      return `${found.label}${effort}`;
    }
    if (profile.model_id === 'deepseek/deepseek-chat') {
      return `opencode-deepseek (OpenRouter)${effort}`;
    }
    if (profile.model_id === 'deepseek-chat') {
      return `opencode-deepseek (API)${effort}`;
    }
    if (profile.model_id === 'deepseek-reasoner') {
      return `opencode-deepseek-r1 (API)${effort}`;
    }
    return `${profile.agent_id} (${profile.model_id})${effort}`;
  }

  selectProject(projectId: string) {
    this.refresh.setSelectedProject(projectId);
  }

  openBacklog() {
    void this.router.navigate(['/backlog']);
  }

  openCreateModal() {
    this.newProject = {
      project_id: '',
      display_name: '',
      repository: '',
      base_branch: 'main',
    };
    this.newProjectProfiles = {
      thinking: 'gpt-5.6-luna',
      execution: 'gpt-5.6-luna',
      independent_review: 'claude-sonnet-5-5-medium',
      fallback: 'gpt-5.6-luna',
    };
    this.showCreateModal = true;
  }

  openEditModal() {
    const proj = this.refresh.activeProject();
    if (!proj) return;
    this.editProject = {
      project_id: proj.project_id,
      display_name: proj.display_name || proj.name || proj.project_id,
      base_branch: proj.base_branch || 'main',
    };

    const profiles = proj.agent_profiles || {};
    this.editProjectProfiles = {
      thinking: profiles['thinking']?.model_id || 'gpt-5.6-luna',
      execution: profiles['execution']?.model_id || 'gpt-5.6-luna',
      independent_review: profiles['independent_review']?.model_id || 'claude-sonnet-5-5-medium',
      fallback: profiles['fallback']?.model_id || 'gpt-5.6-luna',
    };
    this.showEditModal = true;
  }

  resolveAgentForModel(modelId: string): string {
    const found = this.availableModels.find(m => m.id === modelId);
    if (found) return found.agent;
    if (modelId.includes('deepseek')) return 'opencode';
    if (modelId.includes('gemini') || modelId.includes('claude') || modelId.includes('oss')) return 'antigravity';
    return 'codex';
  }

  private buildProfile(role: string, modelId: string) {
    const found = this.availableModels.find(m => m.id === modelId);
    let agent_id = found?.agent;
    if (!agent_id) {
      if (modelId.includes('deepseek')) {
        agent_id = 'opencode';
      } else if (modelId.includes('gemini') || modelId.includes('claude') || modelId.includes('oss')) {
        agent_id = 'antigravity';
      } else {
        agent_id = 'codex';
      }
    }

    let effort = 'medium';
    if (modelId.endsWith('-high')) effort = 'high';
    else if (modelId.endsWith('-low')) effort = 'low';
    else if (modelId.endsWith('-medium')) effort = 'medium';
    else if (found?.effort) effort = found.effort;

    let workflows: string[] = [];
    let skills: string[] = [];

    if (agent_id === 'antigravity') {
      if (role === 'independent_review') {
        workflows = ['/opsx-verify'];
      } else if (role === 'thinking') {
        workflows = ['/opsx-explore', '/opsx-propose'];
      } else {
        workflows = ['/opsx-apply', '/opsx-update'];
      }
      skills = [];
    } else {
      if (role === 'independent_review') {
        workflows = ['$openspec-verify-change'];
        skills = ['openspec-verify-change'];
      } else if (role === 'thinking') {
        workflows = ['$openspec-explore', '$openspec-propose'];
        skills = ['openspec-explore', 'openspec-propose'];
      } else {
        workflows = ['$openspec-apply-change', '$openspec-update-change'];
        skills = ['openspec-apply-change', 'openspec-update-change'];
      }
    }

    return {
      agent_id,
      model_id: modelId,
      effort,
      workflows,
      skills,
    };
  }

  async submitCreateProject() {
    if (this.isReviewerConflict(this.newProjectProfiles)) {
      this.actionOk.set(false);
      this.actionMsg.set('Conflicto de Independencia: La revisión independiente debe ser de un proveedor distinto a la ejecución.');
      return;
    }

    this.isActionRunning.set(true);
    this.actionMsg.set(null);

    const payload = {
      project_id: this.newProject.project_id.trim(),
      display_name: this.newProject.display_name.trim(),
      project_type: 'BROWNFIELD',
      repository: this.newProject.repository.trim(),
      base_branch: this.newProject.base_branch.trim() || 'main',
      provider_connections: {
        tickets: { provider_id: 'github', secret_reference: null },
        git_pr: { provider_id: 'github', secret_reference: null },
      },
      agent_profiles: {
        thinking: this.buildProfile('thinking', this.newProjectProfiles.thinking),
        execution: this.buildProfile('execution', this.newProjectProfiles.execution),
        independent_review: this.buildProfile('independent_review', this.newProjectProfiles.independent_review),
        fallback: this.buildProfile('fallback', this.newProjectProfiles.fallback),
      },
      execution_policy: {
        max_review_rounds: 2,
        max_correction_attempts: 1,
        code_review_policy: 'risk_based',
        fallback_authorized: false,
      },
    };

    try {
      const res = await this.api.post('/api/v1/projects', payload);
      if (res.ok) {
        this.actionOk.set(true);
        this.actionMsg.set(`Proyecto '${payload.project_id}' registrado exitosamente.`);
        this.showCreateModal = false;
        await this.refresh.read();
        this.refresh.setSelectedProject(payload.project_id);
      } else {
        this.actionOk.set(false);
        this.actionMsg.set(`Error al registrar proyecto: ${res.error || 'Verifica los datos'}`);
      }
    } catch (e: any) {
      this.actionOk.set(false);
      this.actionMsg.set(`Error de conexión: ${e.message || e}`);
    } finally {
      this.isActionRunning.set(false);
    }
  }

  async submitEditProject() {
    if (this.isReviewerConflict(this.editProjectProfiles)) {
      this.actionOk.set(false);
      this.actionMsg.set('Conflicto de Independencia: La revisión independiente debe ser de un proveedor distinto a la ejecución.');
      return;
    }

    this.isActionRunning.set(true);
    this.actionMsg.set(null);

    const proj = this.refresh.activeProject();
    if (!proj) return;

    const payload = {
      display_name: this.editProject.display_name.trim(),
      base_branch: this.editProject.base_branch.trim() || 'main',
      agent_profiles: {
        thinking: this.buildProfile('thinking', this.editProjectProfiles.thinking),
        execution: this.buildProfile('execution', this.editProjectProfiles.execution),
        independent_review: this.buildProfile('independent_review', this.editProjectProfiles.independent_review),
        fallback: this.buildProfile('fallback', this.editProjectProfiles.fallback),
      },
    };

    try {
      const res = await this.api.patch(`/api/v1/projects/${encodeURIComponent(proj.project_id)}`, payload);
      if (res.ok) {
        this.actionOk.set(true);
        this.actionMsg.set(`Proyecto '${proj.project_id}' actualizado con nuevos modelos y ajustes.`);
        this.showEditModal = false;
        await this.refresh.read();
      } else {
        this.actionOk.set(false);
        this.actionMsg.set(`Error al actualizar proyecto: ${res.error || 'Verifica los parámetros'}`);
      }
    } catch (e: any) {
      this.actionOk.set(false);
      this.actionMsg.set(`Error de conexión: ${e.message || e}`);
    } finally {
      this.isActionRunning.set(false);
    }
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
