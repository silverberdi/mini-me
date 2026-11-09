import { Component, signal, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule, Router } from '@angular/router';
import { RefreshService } from '../../core/refresh.service';
import { ApiService } from '../../core/api.service';
import { ProjectAgentProfile, ProjectExecutionPolicy } from '../../core/models';
import { ModelComboboxComponent, ModelOption } from '../../shared/model-combobox.component';

@Component({
  selector: 'app-proyectos',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, ModelComboboxComponent],
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

      <div *ngIf="isGlobalPauseActive()"
           class="px-4 py-3 rounded-xl bg-amber-500/10 text-amber-300 border border-amber-500/30 text-sm font-semibold"
           role="status">
        Pausado globalmente
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
            <span *ngIf="proj.execution_policy?.effective_pause === true"
                  class="inline-flex mt-2 px-2.5 py-0.5 text-xs font-semibold rounded-full bg-amber-500/10 text-amber-300 border border-amber-500/30"
                  role="status">
              Pausado
            </span>

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
            <h3 class="font-bold text-slate-200">Modelos Asignados por Rol</h3>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-3.5">
              <div class="space-y-1 bg-slate-800/40 p-2.5 rounded-xl border border-slate-800">
                <app-model-combobox
                  label="Thinking (Exploración)"
                  [models]="availableModels"
                  [(modelValue)]="newProjectProfiles.thinking"
                ></app-model-combobox>
                <div class="flex items-center gap-2 text-[10px] text-slate-400 font-mono pt-1 border-t border-slate-800/60">
                  <span class="text-slate-500">Esfuerzo:</span>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="new_effort_thinking" value="low" [(ngModel)]="newProjectEfforts.thinking" class="text-sky-500 focus:ring-0"> Bajo
                  </label>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="new_effort_thinking" value="medium" [(ngModel)]="newProjectEfforts.thinking" class="text-sky-500 focus:ring-0"> Medio
                  </label>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="new_effort_thinking" value="high" [(ngModel)]="newProjectEfforts.thinking" class="text-sky-500 focus:ring-0"> Alto
                  </label>
                </div>
              </div>

              <div class="space-y-1 bg-slate-800/40 p-2.5 rounded-xl border border-slate-800">
                <app-model-combobox
                  label="Execution (Código)"
                  [models]="availableModels"
                  [(modelValue)]="newProjectProfiles.execution"
                ></app-model-combobox>
                <div class="flex items-center gap-2 text-[10px] text-slate-400 font-mono pt-1 border-t border-slate-800/60">
                  <span class="text-slate-500">Esfuerzo:</span>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="new_effort_execution" value="low" [(ngModel)]="newProjectEfforts.execution" class="text-sky-500 focus:ring-0"> Bajo
                  </label>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="new_effort_execution" value="medium" [(ngModel)]="newProjectEfforts.execution" class="text-sky-500 focus:ring-0"> Medio
                  </label>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="new_effort_execution" value="high" [(ngModel)]="newProjectEfforts.execution" class="text-sky-500 focus:ring-0"> Alto
                  </label>
                </div>
              </div>

              <div class="space-y-1 bg-slate-800/40 p-2.5 rounded-xl border border-slate-800">
                <app-model-combobox
                  label="Review (Revisión Independiente)"
                  [models]="availableModels"
                  [(modelValue)]="newProjectProfiles.independent_review"
                ></app-model-combobox>
                <div class="flex items-center gap-2 text-[10px] text-slate-400 font-mono pt-1 border-t border-slate-800/60">
                  <span class="text-slate-500">Esfuerzo:</span>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="new_effort_review" value="low" [(ngModel)]="newProjectEfforts.independent_review" class="text-sky-500 focus:ring-0"> Bajo
                  </label>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="new_effort_review" value="medium" [(ngModel)]="newProjectEfforts.independent_review" class="text-sky-500 focus:ring-0"> Medio
                  </label>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="new_effort_review" value="high" [(ngModel)]="newProjectEfforts.independent_review" class="text-sky-500 focus:ring-0"> Alto
                  </label>
                </div>
              </div>

              <div class="space-y-1 bg-slate-800/40 p-2.5 rounded-xl border border-slate-800">
                <app-model-combobox
                  label="Fallback (Respaldo)"
                  [models]="availableModels"
                  [(modelValue)]="newProjectProfiles.fallback"
                ></app-model-combobox>
                <div class="flex items-center gap-2 text-[10px] text-slate-400 font-mono pt-1 border-t border-slate-800/60">
                  <span class="text-slate-500">Esfuerzo:</span>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="new_effort_fallback" value="low" [(ngModel)]="newProjectEfforts.fallback" class="text-sky-500 focus:ring-0"> Bajo
                  </label>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="new_effort_fallback" value="medium" [(ngModel)]="newProjectEfforts.fallback" class="text-sky-500 focus:ring-0"> Medio
                  </label>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="new_effort_fallback" value="high" [(ngModel)]="newProjectEfforts.fallback" class="text-sky-500 focus:ring-0"> Alto
                  </label>
                </div>
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
              <p>• <strong>OpenCode CLI</strong>: Ejecuta modelos API externos (<strong class="text-sky-300">DeepSeek (API directa)</strong> y <strong class="text-sky-300">DeepSeek (OpenRouter)</strong>).</p>
              <p>• <strong>Anthropic Claude & Google Gemini</strong>: Operan vía el harness <strong>Antigravity</strong> con capacidades OpenSpec.</p>
              <p>• <strong>OpenAI GPT</strong>: Opera vía el harness <strong>Codex</strong>.</p>
              <p>• <strong>DeepSeek Directo</strong>: Auditor de solo lectura (<code class="text-sky-300">CONTRACT_REVIEW</code> y <code class="text-sky-300">REVIEW</code>).</p>
            </div>

            <!-- Stepper de 4 Etapas de Creación -->
            <div *ngIf="isActionRunning() || creationStep() > 0" class="p-3.5 bg-slate-800/80 rounded-xl border border-slate-700 space-y-2.5">
              <span class="text-[11px] font-bold text-sky-300 uppercase tracking-wider block">Progreso de Creación Guiada</span>
              <div class="space-y-2">
                <div *ngFor="let st of createStages; let i = index" class="flex items-start gap-2.5 text-xs">
                  <div class="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 mt-0.5"
                       [ngClass]="{
                         'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40': creationStep() > i + 1,
                         'bg-sky-500 text-slate-950 animate-pulse font-bold': creationStep() === i + 1 && isActionRunning(),
                         'bg-slate-800 text-slate-500 border border-slate-700': creationStep() < i + 1
                       }">
                    {{ creationStep() > i + 1 ? '✓' : (i + 1) }}
                  </div>
                  <div>
                    <span class="font-medium block"
                          [ngClass]="{
                            'text-emerald-400': creationStep() > i + 1,
                            'text-sky-300 font-bold': creationStep() === i + 1 && isActionRunning(),
                            'text-slate-400': creationStep() < i + 1
                          }">
                      {{ st.label }}
                    </span>
                    <span class="text-[11px] text-slate-400 block">{{ st.desc }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- Modal Error Feedback -->
            <div *ngIf="actionMsg() && !actionOk()" role="alert"
                 class="p-3 rounded-xl bg-red-500/15 border border-red-500/30 text-red-300 text-xs flex items-center justify-between gap-2">
              <div class="flex items-center gap-2">
                <span>⚠️</span>
                <span>{{ actionMsg() }}</span>
              </div>
              <button type="button" (click)="clearActionMsg()" class="text-red-400 hover:text-red-200 text-sm font-bold ml-2">✕</button>
            </div>

            <!-- Guidance for GitHub App Permission Grants -->
            <div *ngIf="actionMsg() && !actionOk() && isGitHubGrantError(actionMsg())"
                 class="p-3 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs space-y-1.5">
              <div class="font-bold flex items-center gap-1.5">
                <span>🔐</span>
                <span>Autorización de GitHub requerida</span>
              </div>
              <p>La GitHub App de mini me necesita acceso explícito a este repositorio. Puedes habilitarlo en GitHub:</p>
              <ol class="list-decimal list-inside pl-1 space-y-0.5 text-[11px] text-amber-200">
                <li>Ve a <strong>GitHub &rarr; Settings &rarr; Applications &rarr; Installed GitHub Apps</strong></li>
                <li>Selecciona la instalación de <strong>mini me</strong> &rarr; sección <em>Repository Access</em></li>
                <li>Elige <strong>All repositories</strong> o añade este repositorio a la lista seleccionada.</li>
              </ol>
            </div>
          </div>

          <div class="pt-4 flex items-center justify-end gap-3">
            <button type="button" (click)="showCreateModal = false"
                    class="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold cursor-pointer">
              Cancelar
            </button>
            <button type="submit" [disabled]="isActionRunning() || !isFormValid(newProjectProfiles)"
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
            <h3 class="font-bold text-slate-200">Asignación de Modelos por Rol</h3>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-3.5">
              <div class="space-y-1 bg-slate-800/40 p-2.5 rounded-xl border border-slate-800">
                <app-model-combobox
                  label="Thinking (Exploración)"
                  [models]="availableModels"
                  [(modelValue)]="editProjectProfiles.thinking"
                ></app-model-combobox>
                <div class="flex items-center gap-2 text-[10px] text-slate-400 font-mono pt-1 border-t border-slate-800/60">
                  <span class="text-slate-500">Esfuerzo:</span>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="edit_effort_thinking" value="low" [(ngModel)]="editProjectEfforts.thinking" class="text-sky-500 focus:ring-0"> Bajo
                  </label>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="edit_effort_thinking" value="medium" [(ngModel)]="editProjectEfforts.thinking" class="text-sky-500 focus:ring-0"> Medio
                  </label>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="edit_effort_thinking" value="high" [(ngModel)]="editProjectEfforts.thinking" class="text-sky-500 focus:ring-0"> Alto
                  </label>
                </div>
              </div>

              <div class="space-y-1 bg-slate-800/40 p-2.5 rounded-xl border border-slate-800">
                <app-model-combobox
                  label="Execution (Código)"
                  [models]="availableModels"
                  [(modelValue)]="editProjectProfiles.execution"
                ></app-model-combobox>
                <div class="flex items-center gap-2 text-[10px] text-slate-400 font-mono pt-1 border-t border-slate-800/60">
                  <span class="text-slate-500">Esfuerzo:</span>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="edit_effort_execution" value="low" [(ngModel)]="editProjectEfforts.execution" class="text-sky-500 focus:ring-0"> Bajo
                  </label>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="edit_effort_execution" value="medium" [(ngModel)]="editProjectEfforts.execution" class="text-sky-500 focus:ring-0"> Medio
                  </label>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="edit_effort_execution" value="high" [(ngModel)]="editProjectEfforts.execution" class="text-sky-500 focus:ring-0"> Alto
                  </label>
                </div>
              </div>

              <div class="space-y-1 bg-slate-800/40 p-2.5 rounded-xl border border-slate-800">
                <app-model-combobox
                  label="Review (Revisión Independiente)"
                  [models]="availableModels"
                  [(modelValue)]="editProjectProfiles.independent_review"
                ></app-model-combobox>
                <div class="flex items-center gap-2 text-[10px] text-slate-400 font-mono pt-1 border-t border-slate-800/60">
                  <span class="text-slate-500">Esfuerzo:</span>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="edit_effort_review" value="low" [(ngModel)]="editProjectEfforts.independent_review" class="text-sky-500 focus:ring-0"> Bajo
                  </label>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="edit_effort_review" value="medium" [(ngModel)]="editProjectEfforts.independent_review" class="text-sky-500 focus:ring-0"> Medio
                  </label>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="edit_effort_review" value="high" [(ngModel)]="editProjectEfforts.independent_review" class="text-sky-500 focus:ring-0"> Alto
                  </label>
                </div>
              </div>

              <div class="space-y-1 bg-slate-800/40 p-2.5 rounded-xl border border-slate-800">
                <app-model-combobox
                  label="Fallback (Respaldo)"
                  [models]="availableModels"
                  [(modelValue)]="editProjectProfiles.fallback"
                ></app-model-combobox>
                <div class="flex items-center gap-2 text-[10px] text-slate-400 font-mono pt-1 border-t border-slate-800/60">
                  <span class="text-slate-500">Esfuerzo:</span>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="edit_effort_fallback" value="low" [(ngModel)]="editProjectEfforts.fallback" class="text-sky-500 focus:ring-0"> Bajo
                  </label>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="edit_effort_fallback" value="medium" [(ngModel)]="editProjectEfforts.fallback" class="text-sky-500 focus:ring-0"> Medio
                  </label>
                  <label class="inline-flex items-center gap-1 cursor-pointer hover:text-slate-200">
                    <input type="radio" name="edit_effort_fallback" value="high" [(ngModel)]="editProjectEfforts.fallback" class="text-sky-500 focus:ring-0"> Alto
                  </label>
                </div>
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
              <p>• <strong>OpenCode CLI</strong>: Ejecuta modelos API externos (<strong class="text-sky-300">DeepSeek (API directa)</strong> y <strong class="text-sky-300">DeepSeek (OpenRouter)</strong>).</p>
              <p>• <strong>Anthropic Claude & Google Gemini</strong>: Operan vía el harness <strong>Antigravity</strong> con capacidades OpenSpec.</p>
              <p>• <strong>OpenAI GPT</strong>: Opera vía el harness <strong>Codex</strong>.</p>
              <p>• <strong>DeepSeek Directo</strong>: Auditor de solo lectura (<code class="text-sky-300">CONTRACT_REVIEW</code> y <code class="text-sky-300">REVIEW</code>).</p>
            </div>

            <!-- Modal Error Feedback -->
            <div *ngIf="actionMsg() && !actionOk()" role="alert"
                 class="p-3 rounded-xl bg-red-500/15 border border-red-500/30 text-red-300 text-xs flex items-center justify-between gap-2">
              <div class="flex items-center gap-2">
                <span>⚠️</span>
                <span>{{ actionMsg() }}</span>
              </div>
              <button type="button" (click)="clearActionMsg()" class="text-red-400 hover:text-red-200 text-sm font-bold ml-2">✕</button>
            </div>
          </div>

          <div class="pt-4 flex items-center justify-end gap-3">
            <button type="button" (click)="showEditModal = false"
                    class="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold cursor-pointer">
              Cancelar
            </button>
            <button type="submit" [disabled]="isActionRunning() || !isFormValid(editProjectProfiles)"
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

  createStages = [
    { key: 'connection', label: '1. Conexión GitHub & Grants', desc: 'Validación de acceso al repositorio y permisos (issues, contents, PRs)' },
    { key: 'repository', label: '2. Repositorio Gestionado', desc: 'Aprovisionamiento de clon base y binding duradero' },
    { key: 'skills', label: '3. Aprovisionamiento de Skills', desc: 'Instalación de capacidades canónicas (Codex, Antigravity, OpenCode)' },
    { key: 'readiness', label: '4. Verificación de Preparación', desc: 'Comprobación de workflows y legibilidad de archivos' },
  ];
  creationStep = signal<number>(0);

  isGitHubGrantError(msg: string | null): boolean {
    if (!msg) return false;
    const lower = msg.toLowerCase();
    return lower.includes('github app') || lower.includes('permisos') || lower.includes('all repositories') || lower.includes('grants');
  }

  showCreateModal = false;
  showEditModal = false;

  // Available models catalog for selection (loaded authoritatively from backend)
  availableModels: ModelOption[] = [];
  isCatalogLoading = signal(false);

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

  newProjectEfforts = {
    thinking: 'medium',
    execution: 'medium',
    independent_review: 'medium',
    fallback: 'medium',
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

  editProjectEfforts = {
    thinking: 'medium',
    execution: 'medium',
    independent_review: 'medium',
    fallback: 'medium',
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

  isGlobalPauseActive(): boolean {
    return this.refresh.projects().some(project => project.execution_policy?.global_pause === true);
  }

  async ngOnInit(): Promise<void> {
    await Promise.all([
      this.loadAgentsCatalog(),
      this.refresh.projects().length === 0 ? this.refresh.refreshProjects() : Promise.resolve(),
    ]);
  }

  formatModelEntry(modelKey: string, providerId: string, routes: Record<string, string>, efforts: string[]): {
    label: string;
    group: string;
    provider_id: string;
    harness_id: string;
    route?: string;
    effort: string;
  } {
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

    const route = routes[modelKey] || '';

    if (providerId === 'opencode') {
      const isOpenRouter = route === 'openrouter' || modelKey.startsWith('openrouter/');
      const isDirectDeepseek = route === 'deepseek_direct' || modelKey.startsWith('deepseek/');
      const isNative = route === 'opencode_native' || modelKey.startsWith('opencode/');

      if (isOpenRouter) {
        let clean = modelKey.replace(/^openrouter\//, '').replace(/^~/, '');
        const parts = clean.split('/');
        let vendor = '';
        let model = clean;
        if (parts.length >= 2) {
          vendor = parts[0];
          model = parts.slice(1).join('/');
        }
        const cleanModel = model
          .replace(/-latest$/, '')
          .split(/[-_]/)
          .map(w => (/^\d+/i.test(w) || ['gpt', 'oss', 'glm', 'vl'].includes(w.toLowerCase()) ? w.toUpperCase() : w.charAt(0).toUpperCase() + w.slice(1)))
          .join(' ');
        const cleanVendor = vendor ? vendor.charAt(0).toUpperCase() + vendor.slice(1) : '';
        const displayLabel = cleanVendor ? `OpenRouter — ${cleanModel} (${cleanVendor})` : `OpenRouter — ${cleanModel}`;

        return {
          label: displayLabel,
          group: 'OpenRouter (vía OpenCode)',
          provider_id: 'openrouter',
          harness_id: 'opencode',
          route: 'openrouter',
          effort,
        };
      }

      if (isDirectDeepseek) {
        const cleanName = this.friendlyDeepseekName(modelKey);
        return {
          label: `DeepSeek — ${cleanName || 'V4 Pro'} (API directa vía OpenCode)`,
          group: 'DeepSeek — API directa (vía OpenCode)',
          provider_id: 'deepseek',
          harness_id: 'opencode',
          route: 'deepseek_direct',
          effort,
        };
      }

      if (isNative) {
        const cleanName = modelKey.replace(/^opencode\//, '');
        return {
          label: `OpenCode — ${cleanName} (Nativo)`,
          group: 'OpenCode Nativo',
          provider_id: 'opencode',
          harness_id: 'opencode',
          route: 'opencode_native',
          effort,
        };
      }

      return {
        label: `${modelKey} (OpenCode)`,
        group: 'OpenCode · Otros',
        provider_id: 'opencode',
        harness_id: 'opencode',
        route,
        effort,
      };
    }

    if (providerId === 'codex') {
      const sub = modelKey.replace(/^gpt-/, '').toUpperCase();
      return {
        label: `Codex — GPT-${sub}`,
        group: 'OpenAI GPT (vía Codex)',
        provider_id: 'codex',
        harness_id: 'codex',
        route: 'native',
        effort,
      };
    }

    if (providerId === 'antigravity') {
      let group = 'Antigravity';
      let label = `Antigravity — ${modelKey}`;
      if (modelKey.startsWith('claude')) {
        group = 'Anthropic Claude (vía Antigravity)';
        const sub = modelKey.replace(/^claude-/, '').replace(/-[a-z]+$/, '');
        label = `Antigravity — Claude ${sub.replace('-', '.').toUpperCase()}`;
      } else if (modelKey.startsWith('gemini')) {
        group = 'Google Gemini (vía Antigravity)';
        const sub = modelKey.replace(/^gemini-/, '').replace(/-[a-z]+$/, '');
        label = `Antigravity — Gemini ${sub.toUpperCase()}`;
      } else if (modelKey.includes('oss')) {
        group = 'Open Source (vía Antigravity)';
        label = `Antigravity — GPT-OSS 120B`;
      }
      return {
        label,
        group,
        provider_id: 'antigravity',
        harness_id: 'antigravity',
        route: 'native',
        effort,
      };
    }

    return {
      label: `${providerId} / ${modelKey}`,
      group: 'Otros',
      provider_id: providerId,
      harness_id: providerId,
      route,
      effort,
    };
  }

  async loadAgentsCatalog(): Promise<void> {
    try {
      this.isCatalogLoading.set(true);
      const res = await this.api.get<any>('/api/v1/catalogs/agents');
      if (res.ok && res.data?.agents) {
        const parsedMap = new Map<string, ModelOption>();
        for (const agent of res.data.agents) {
          const providerId = (agent.id || '').toLowerCase();
          const modelsObj = agent.models || {};
          const routes: Record<string, string> = agent.model_routes || {};
          for (const modelKey of Object.keys(modelsObj)) {
            const efforts: string[] = modelsObj[modelKey] || [];
            const entry = this.formatModelEntry(modelKey, providerId, routes, efforts);
            const dedupKey = `${providerId}:${entry.label}:${entry.group}`;

            if (parsedMap.has(dedupKey)) {
              const existing = parsedMap.get(dedupKey)!;
              if (existing.variants) {
                existing.variants[entry.effort] = modelKey;
              }
              if (entry.effort === 'medium') {
                existing.id = modelKey;
              }
            } else {
              const variants: Record<string, string> = { [entry.effort]: modelKey };
              parsedMap.set(dedupKey, {
                id: modelKey,
                agent: providerId,
                ...entry,
                variants,
              });
            }
          }
        }
        if (parsedMap.size > 0) {
          this.availableModels = Array.from(parsedMap.values()).sort(
            (a, b) => a.group.localeCompare(b.group) || a.label.localeCompare(b.label)
          );
        }
      }
    } catch {
      // Keep existing models
    } finally {
      this.isCatalogLoading.set(false);
    }
  }

  resolveProviderForModel(modelId: string): string {
    const found = this.availableModels.find(
      m => m.id === modelId || (m.variants !== undefined && Object.values(m.variants).includes(modelId))
    );
    if (found?.provider_id) return found.provider_id;
    if (modelId.startsWith('openrouter/')) return 'openrouter';
    if (modelId.startsWith('deepseek/') || modelId.startsWith('deepseek-')) return 'deepseek';
    if (modelId.startsWith('gpt-')) return 'codex';
    if (modelId.startsWith('claude-') || modelId.startsWith('gemini-')) return 'antigravity';
    return found?.agent || '';
  }

  isReviewerConflict(profiles: { thinking: string; execution: string; independent_review: string }): boolean {
    const execProvider = this.resolveProviderForModel(profiles.execution);
    const thinkProvider = this.resolveProviderForModel(profiles.thinking);
    const reviewProvider = this.resolveProviderForModel(profiles.independent_review);
    if (!reviewProvider || !execProvider) return false;
    return reviewProvider === execProvider || reviewProvider === thinkProvider;
  }

  friendlyDeepseekName(modelKey: string): string {
    // Derive a short human name from the last path segment, e.g.
    // deepseek/deepseek-v4-pro -> "V4 Pro", openrouter/deepseek/deepseek-v4-pro -> "V4 Pro".
    const segments = modelKey.split('/').filter(s => s && s !== 'deepseek');
    const last = segments[segments.length - 1] || modelKey;
    const cleaned = last.replace(/^deepseek-/, '').replace(/-latest$/, '').replace(/-/g, ' ');
    return cleaned.split(' ').filter(Boolean).map(w => w[0].toUpperCase() + w.slice(1)).join(' ');
  }

  getRoleModel(role: string): string {
    const proj = this.refresh.activeProject();
    if (!proj || !proj.agent_profiles) return 'Configuración por defecto';
    const profile = proj.agent_profiles[role];
    if (!profile) return 'No asignado';
    const found = this.availableModels.find(
      m => m.id === profile.model_id || (m.variants !== undefined && Object.values(m.variants).includes(profile.model_id))
    );
    const effort = profile.effort ? ` [${profile.effort.slice(0, 3)}]` : '';
    if (found) {
      return `${found.label}${effort}`;
    }
    // Legacy persisted ids: translate to the operator-friendly deepseek routes.
    const legacyRoutes: Record<string, string> = {
      'deepseek-chat': 'DeepSeek — API directa (vía OpenCode)',
      'deepseek-reasoner': 'DeepSeek R1 — API directa (vía OpenCode)',
      'deepseek/deepseek-chat': 'DeepSeek — OpenRouter (vía OpenCode)',
      'deepseek-flash': 'DeepSeek Flash — API directa (vía OpenCode)',
      'deepseek-v4-pro': 'DeepSeek V4 Pro — API directa (vía OpenCode)',
    };
    if (legacyRoutes[profile.model_id]) {
      return `${legacyRoutes[profile.model_id]}${effort}`;
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
    this.creationStep.set(0);
    this.actionMsg.set(null);
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
    this.newProjectEfforts = {
      thinking: 'medium',
      execution: 'medium',
      independent_review: 'medium',
      fallback: 'medium',
    };
    this.showCreateModal = true;
  }

  clearActionMsg(): void {
    this.actionMsg.set(null);
  }

  openEditModal() {
    this.actionMsg.set(null);
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
    this.editProjectEfforts = {
      thinking: profiles['thinking']?.effort || 'medium',
      execution: profiles['execution']?.effort || 'medium',
      independent_review: profiles['independent_review']?.effort || 'medium',
      fallback: profiles['fallback']?.effort || 'medium',
    };
    this.showEditModal = true;
  }

  isFormValid(profiles: { thinking: string; execution: string; independent_review: string; fallback: string }): boolean {
    if (!profiles.thinking || !profiles.execution || !profiles.independent_review || !profiles.fallback) return false;
    for (const role of ['thinking', 'execution', 'independent_review', 'fallback'] as const) {
      const modelKey = profiles[role];
      const found = this.availableModels.find(
        m => m.id === modelKey || (m.variants !== undefined && Object.values(m.variants).includes(modelKey))
      );
      if (!found || !found.provider_id || !found.harness_id) return false;
    }
    return !this.isReviewerConflict(profiles);
  }

  resolveAgentForModel(modelId: string): string {
    const found = this.availableModels.find(
      m => m.id === modelId || (m.variants !== undefined && Object.values(m.variants).includes(modelId))
    );
    if (found) return found.agent;
    const legacyRoutes: Record<string, string> = {
      'deepseek-chat': 'deepseek',
      'deepseek-reasoner': 'openrouter',
      'deepseek-flash': 'deepseek',
      'deepseek-v4-pro': 'deepseek',
    };
    return legacyRoutes[modelId] || '';
  }

  private buildProfile(role: string, modelId: string, effortVal?: string, isNew = false) {
    const proj = isNew ? null : this.refresh.activeProject();
    const existing = proj?.agent_profiles?.[role];
    const found = this.availableModels.find(
      m => m.id === modelId || (m.variants !== undefined && Object.values(m.variants).includes(modelId))
    );

    let effort = effortVal || 'medium';
    if (!effortVal) {
      if (modelId.endsWith('-high')) effort = 'high';
      else if (modelId.endsWith('-low')) effort = 'low';
      else if (modelId.endsWith('-medium')) effort = 'medium';
      else if (found?.effort) effort = found.effort;
      else if (existing?.effort) effort = existing.effort;
    }

    let targetModelId = modelId;
    if (found?.variants && found.variants[effort]) {
      targetModelId = found.variants[effort];
    } else if (found?.agent === 'antigravity') {
      const baseName = (found?.id || modelId).replace(/-(low|medium|high)$/, '');
      targetModelId = `${baseName}-${effort}`;
    }

    if (existing && existing.model_id === modelId && existing.effort === effort && existing.provider_id && existing.harness_id) {
      return existing;
    }
    if (existing && existing.model_id === targetModelId && existing.effort === effort && existing.provider_id && existing.harness_id) {
      return existing;
    }

    let agent_id = found?.agent;
    if (!agent_id) agent_id = this.resolveAgentForModel(targetModelId);

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
    } else if (agent_id) {
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
    } else {
      // Unknown identifiers remain invalid; the backend validates the exact
      // canonical provider/harness/model identity before persistence.
      workflows = [];
      skills = [];
    }

    const provider_id =
      found?.provider_id ||
      (agent_id === 'opencode' && modelId.startsWith('openrouter/')
        ? 'openrouter'
        : agent_id === 'opencode' && modelId.startsWith('deepseek/')
        ? 'deepseek'
        : agent_id);
    const harness_id = found?.harness_id || agent_id;
    const route =
      found?.route ||
      (provider_id === 'openrouter'
        ? 'openrouter'
        : provider_id === 'deepseek'
        ? 'deepseek_direct'
        : undefined);

    return {
      agent_id,
      model_id: targetModelId,
      provider_id,
      harness_id,
      route,
      effort,
      workflows,
      skills,
    };
  }

  async submitCreateProject() {
    if (!this.isFormValid(this.newProjectProfiles)) {
      this.actionOk.set(false);
      this.actionMsg.set('Configuración incompleta: selecciona un modelo válido para cada rol.');
      return;
    }

    if (this.isReviewerConflict(this.newProjectProfiles)) {
      this.actionOk.set(false);
      this.actionMsg.set('Conflicto de Independencia: La revisión independiente debe ser de un proveedor distinto a la ejecución.');
      return;
    }

    this.isActionRunning.set(true);
    this.actionMsg.set(null);
    this.creationStep.set(1);

    const payload = {
      project_id: this.newProject.project_id.trim(),
      display_name: this.newProject.display_name.trim(),
      project_type: 'BROWNFIELD',
      repository: this.newProject.repository.trim(),
      base_branch: this.newProject.base_branch.trim() || 'main',
      provider_connections: {
        tickets: { provider_id: 'github', repository_url: this.newProject.repository.trim(), auth_mode: 'environment_app', secret_reference: null },
        git_pr: { provider_id: 'github', repository_url: this.newProject.repository.trim(), auth_mode: 'environment_app', secret_reference: null },
      },
      agent_profiles: {
        thinking: this.buildProfile('thinking', this.newProjectProfiles.thinking, this.newProjectEfforts.thinking, true),
        execution: this.buildProfile('execution', this.newProjectProfiles.execution, this.newProjectEfforts.execution, true),
        independent_review: this.buildProfile('independent_review', this.newProjectProfiles.independent_review, this.newProjectEfforts.independent_review, true),
        fallback: this.buildProfile('fallback', this.newProjectProfiles.fallback, this.newProjectEfforts.fallback, true),
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
        await this.refresh.refreshProjects();
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
    if (!this.isFormValid(this.editProjectProfiles)) {
      this.actionOk.set(false);
      this.actionMsg.set('Configuración incompleta: selecciona un modelo válido para cada rol.');
      return;
    }

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
        thinking: this.buildProfile('thinking', this.editProjectProfiles.thinking, this.editProjectEfforts.thinking),
        execution: this.buildProfile('execution', this.editProjectProfiles.execution, this.editProjectEfforts.execution),
        independent_review: this.buildProfile('independent_review', this.editProjectProfiles.independent_review, this.editProjectEfforts.independent_review),
        fallback: this.buildProfile('fallback', this.editProjectProfiles.fallback, this.editProjectEfforts.fallback),
      },
    };

    try {
      const res = await this.api.patch(`/api/v1/projects/${encodeURIComponent(proj.project_id)}`, payload);
      if (res.ok) {
        this.actionOk.set(true);
        this.actionMsg.set(`Proyecto '${proj.project_id}' actualizado con nuevos modelos y ajustes.`);
        this.showEditModal = false;
        await this.refresh.refreshProjects();
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
        await this.refresh.refreshProjects();
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
