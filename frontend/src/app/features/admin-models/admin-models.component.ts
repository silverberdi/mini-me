import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/api.service';
import { Project } from '../../core/models';

interface RegistryModel {
  id: string;
  provider_id: string;
  harness_id: string;
  canonical_model_id: string;
  origin: string;
  capabilities: Record<string, unknown>;
  discovery_status: string;
  is_enabled: boolean;
  version: number;
  diagnostic?: { code: string; summary: string; verified: boolean } | null;
}

interface ProviderCatalog {
  providers: Array<{ id: string; harnesses: string[] }>;
  harnesses: Array<{ id: string; providers: string[] }>;
  models: RegistryModel[];
}

interface HarnessResult {
  harness_id: string;
  status: string;
  code: string;
  summary: string;
}

interface ProviderConnectionDiagnostic {
  provider: string;
  status: 'success' | 'failure' | 'unavailable';
  latency_ms: number | null;
  code: string;
  detail: string;
}

interface AgentCatalogEntry {
  id: string;
  roles: string[];
  file_edit_roles: string[];
  read_only_roles: string[];
  models: Record<string, string[] | null>;
}

interface RoleChoice {
  key: 'thinking' | 'execution' | 'independent_review';
  label: string;
  capability: string[];
  agentRole: string;
}

@Component({
  selector: 'app-admin-models',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <section class="space-y-6 text-slate-100">
      <header class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 class="text-2xl font-bold">Administración / Modelos &amp; Proveedores</h1>
          <p class="mt-1 text-sm text-slate-400">Catálogo persistido y asignaciones del proyecto seleccionado.</p>
        </div>
        <button type="button" (click)="refreshHarnesses()" [disabled]="refreshingHarnesses"
                class="rounded-lg border border-sky-500/30 bg-sky-500/10 px-4 py-2 text-sm font-semibold text-sky-200 disabled:opacity-50">
          {{ refreshingHarnesses ? 'Consultando harnesses…' : 'Actualizar estado de harnesses' }}
        </button>
      </header>

      <p *ngIf="errorMessage" role="alert" class="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">{{ errorMessage }}</p>
      <p *ngIf="successMessage" role="status" class="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-200">{{ successMessage }}</p>

      <section aria-labelledby="harness-heading" class="space-y-3">
        <h2 id="harness-heading" class="text-lg font-semibold">Harnesses instalados</h2>
        <div *ngIf="harnessCards().length === 0" class="rounded-xl border border-slate-700 p-4 text-sm text-slate-400">No hay harnesses en el catálogo observado.</div>
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <article *ngFor="let harness of harnessCards()" class="rounded-xl border border-slate-700 bg-slate-800/50 p-4">
            <div class="flex items-center justify-between gap-2">
              <h3 class="font-semibold">{{ harness.harness_id }}</h3>
              <span class="rounded-full bg-slate-700 px-2 py-1 text-xs">{{ harness.status || 'Sin observación' }}</span>
            </div>
            <p class="mt-2 text-sm text-slate-400">{{ harness.summary || 'Actualiza el estado para obtener una observación real.' }}</p>
          </article>
        </div>
      </section>

      <section aria-labelledby="models-heading" class="space-y-3">
        <h2 id="models-heading" class="text-lg font-semibold">Modelos</h2>
        <div class="overflow-x-auto rounded-xl border border-slate-700">
          <table class="w-full min-w-[760px] text-left text-sm">
            <thead class="bg-slate-800 text-xs uppercase text-slate-400"><tr>
              <th class="p-3">Proveedor / modelo</th><th class="p-3">Harness</th><th class="p-3">Descubrimiento</th><th class="p-3">Estado de operador</th><th class="p-3">Conexión</th>
            </tr></thead>
            <tbody>
              <tr *ngFor="let model of catalog?.models" class="border-t border-slate-800">
                <td class="p-3"><div class="font-medium">{{ model.provider_id }} / {{ model.canonical_model_id }}</div><div class="text-xs text-slate-500">{{ model.origin }}</div></td>
                <td class="p-3">{{ model.harness_id }}</td>
                <td class="p-3"><span>{{ model.discovery_status }}</span><span *ngIf="model.diagnostic?.summary" class="mt-1 block max-w-sm text-xs text-slate-400">{{ model.diagnostic?.summary }}</span></td>
                <td class="p-3">
                  <label class="inline-flex items-center gap-2" [attr.aria-label]="(model.is_enabled ? 'Deshabilitar ' : 'Habilitar ') + model.canonical_model_id">
                    <input type="checkbox" [checked]="model.is_enabled" [disabled]="busyModelId === model.id" (change)="toggleModel(model, $event)" class="h-4 w-4 rounded border-slate-600 bg-slate-800 text-sky-500">
                    <span>{{ model.is_enabled ? 'Habilitado' : 'Deshabilitado' }}</span>
                  </label>
                </td>
                <td class="p-3">
                  <button type="button" (click)="testConnection(model.provider_id)" [disabled]="testingProviders.has(model.provider_id)"
                          class="rounded-md border border-sky-500/40 px-3 py-1.5 text-xs text-sky-200 disabled:opacity-50">
                    {{ testingProviders.has(model.provider_id) ? 'Probando…' : 'Test Connection' }}
                  </button>
                  <div *ngIf="connectionDiagnostics[model.provider_id] as diagnostic" role="status" class="mt-2 max-w-sm text-xs">
                    <span class="font-semibold">{{ diagnosticStatusLabel(diagnostic.status) }}</span>
                    <span *ngIf="diagnostic.latency_ms !== null" class="ml-2 text-slate-400">{{ diagnostic.latency_ms }} ms</span>
                    <p class="mt-1 text-slate-400">{{ diagnostic.detail }}</p>
                  </div>
                  <p *ngIf="connectionErrors[model.provider_id]" role="alert" class="mt-2 max-w-sm text-xs text-rose-300">
                    {{ connectionErrors[model.provider_id] }}
                  </p>
                </td>
              </tr>
              <tr *ngIf="!catalog?.models?.length"><td colspan="5" class="p-4 text-center text-slate-400">El catálogo aún no contiene modelos.</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="roles-heading" class="space-y-4 rounded-xl border border-slate-700 bg-slate-800/40 p-4 sm:p-6">
        <div>
          <h2 id="roles-heading" class="text-lg font-semibold">Asignación por proyecto</h2>
          <p class="mt-1 text-sm text-slate-400">Los cambios se guardan en el perfil del proyecto mediante la API existente.</p>
        </div>
        <label class="block max-w-xl text-sm">Proyecto
          <select [ngModel]="selectedProjectId" (ngModelChange)="selectProject($event)" class="mt-1 block w-full rounded-lg border border-slate-600 bg-slate-900 p-2.5">
            <option value="">Selecciona un proyecto</option>
            <option *ngFor="let project of projects" [value]="project.project_id">{{ project.display_name || project.name || project.project_id }}</option>
          </select>
        </label>
        <div *ngIf="selectedProjectId" class="grid gap-4 md:grid-cols-3">
          <div *ngFor="let role of roles" class="space-y-2">
            <h3 class="text-sm font-semibold">{{ role.label }}</h3>
            <label class="block text-xs text-slate-400">Proveedor
              <select [ngModel]="roleProviders[role.key] || ''" (ngModelChange)="selectProvider(role, $event)" class="mt-1 block w-full rounded-lg border border-slate-600 bg-slate-900 p-2 text-sm text-slate-100">
                <option value="">Selecciona proveedor</option>
                <option *ngFor="let provider of providersFor(role)" [value]="provider">{{ provider }}</option>
              </select>
            </label>
            <label class="block text-xs text-slate-400">Modelo
              <select [ngModel]="roleModels[role.key] || ''" (ngModelChange)="roleModels[role.key] = $event" class="mt-1 block w-full rounded-lg border border-slate-600 bg-slate-900 p-2 text-sm text-slate-100">
                <option value="">Selecciona modelo</option>
                <option *ngFor="let model of modelsFor(role)" [value]="model.id">{{ model.canonical_model_id }}<ng-container *ngIf="!model.is_enabled"> (deshabilitado actualmente)</ng-container></option>
              </select>
            </label>
          </div>
        </div>
        <p *ngIf="selectedProjectId && !hasEditableProfiles" role="status" class="text-sm text-amber-200">El proyecto no expone los cuatro perfiles necesarios; no se enviarán asignaciones parciales.</p>
        <button type="button" (click)="saveRoleAssignments()" [disabled]="savingRoles || !hasEditableProfiles" class="rounded-lg bg-sky-500 px-4 py-2 text-sm font-bold text-slate-950 disabled:opacity-50">
          {{ savingRoles ? 'Guardando…' : 'Guardar asignaciones' }}
        </button>
      </section>
    </section>
  `
})
export class AdminModelsComponent implements OnInit {
  readonly roles: RoleChoice[] = [
    { key: 'thinking', label: 'Thinker', capability: ['thinking', 'workflow'], agentRole: 'implementer' },
    { key: 'execution', label: 'Implementer', capability: ['file_edit', 'workflow'], agentRole: 'implementer' },
    { key: 'independent_review', label: 'Reviewer', capability: ['read_only_review'], agentRole: 'reviewer' }
  ];

  catalog: ProviderCatalog | null = null;
  projects: Project[] = [];
  project: Project | null = null;
  agentEntries: AgentCatalogEntry[] = [];
  harnessResults: HarnessResult[] | null = null;
  selectedProjectId = '';
  roleProviders: Partial<Record<RoleChoice['key'], string>> = {};
  roleModels: Partial<Record<RoleChoice['key'], string>> = {};
  busyModelId: string | null = null;
  refreshingHarnesses = false;
  savingRoles = false;
  testingProviders = new Set<string>();
  connectionDiagnostics: Record<string, ProviderConnectionDiagnostic> = {};
  connectionErrors: Record<string, string> = {};
  errorMessage = '';
  successMessage = '';

  constructor(private readonly api: ApiService) {}

  async ngOnInit(): Promise<void> {
    const [catalogResponse, projectsResponse, agentsResponse] = await Promise.all([
      this.api.get<ProviderCatalog>('/api/v1/admin/providers/catalog'),
      this.api.get<Project[]>('/api/v1/projects'),
      this.api.get<{ agents: AgentCatalogEntry[] }>('/api/v1/catalogs/agents')
    ]);
    if (!catalogResponse.ok || !projectsResponse.ok || !agentsResponse.ok) {
      this.errorMessage = 'No se pudo cargar el catálogo, los proyectos o las capacidades de agentes.';
      return;
    }
    this.catalog = catalogResponse.data;
    this.projects = projectsResponse.data || [];
    this.agentEntries = agentsResponse.data?.agents || [];
    const preferredProjectId = this.projects[0]?.project_id || '';
    if (preferredProjectId) await this.selectProject(preferredProjectId);
  }

  harnessCards(): Array<{ harness_id: string; status: string; summary: string }> {
    const knownIds = [
      ...(this.catalog?.harnesses || []).map(({ id }) => id),
      ...(this.harnessResults || []).map(({ harness_id }) => harness_id)
    ];
    return [...new Set(knownIds)].map(id => {
      const observed = this.harnessResults?.find(item => item.harness_id === id);
      return {
        harness_id: id,
        status: observed?.status || '',
        summary: observed?.summary || ''
      };
    });
  }

  async refreshHarnesses(): Promise<void> {
    this.refreshingHarnesses = true;
    this.errorMessage = '';
    this.successMessage = '';
    const response = await this.api.post<{ results: HarnessResult[]; catalog: ProviderCatalog }>(
      '/api/v1/admin/providers/refresh', {}
    );
    if (response.ok && response.data) {
      this.harnessResults = response.data.results;
      this.catalog = response.data.catalog;
      this.successMessage = 'Estados actualizados desde la respuesta del servidor.';
    } else {
      this.errorMessage = `No se pudieron actualizar los harnesses: ${response.error || 'error del servidor'}`;
    }
    this.refreshingHarnesses = false;
  }

  async toggleModel(model: RegistryModel, event: Event): Promise<void> {
    const requestedState = (event.target as HTMLInputElement).checked;
    this.busyModelId = model.id;
    this.errorMessage = '';
    this.successMessage = '';
    const response = await this.api.patch<RegistryModel>(
      `/api/v1/admin/providers/models/${encodeURIComponent(model.id)}/enabled`,
      { is_enabled: requestedState, version: model.version }
    );
    if (response.ok && response.data) {
      this.catalog = {
        ...this.catalog!,
        models: (this.catalog?.models || []).map(item => item.id === model.id ? response.data! : item)
      };
      this.successMessage = `${model.canonical_model_id}: estado guardado en el servidor.`;
    } else {
      this.errorMessage = `No se pudo cambiar ${model.canonical_model_id}: ${response.error || 'conflicto o error del servidor'}`;
    }
    this.busyModelId = null;
  }

  async testConnection(providerId: string): Promise<void> {
    delete this.connectionDiagnostics[providerId];
    delete this.connectionErrors[providerId];
    this.testingProviders.add(providerId);
    try {
      const response = await this.api.post<ProviderConnectionDiagnostic>(
        `/api/v1/admin/providers/${encodeURIComponent(providerId)}/test`,
        {}
      );
      if (response.ok && response.data) {
        this.connectionDiagnostics[providerId] = response.data;
      } else {
        this.connectionErrors[providerId] = `No se pudo completar el diagnóstico: ${response.error || 'error del servidor'}`;
      }
    } catch {
      this.connectionErrors[providerId] = 'No se pudo completar el diagnóstico por un error inesperado.';
    } finally {
      this.testingProviders.delete(providerId);
    }
  }

  diagnosticStatusLabel(status: ProviderConnectionDiagnostic['status']): string {
    if (status === 'success') return 'Conexión verificada';
    if (status === 'failure') return 'Error de conexión';
    return 'No disponible';
  }

  async selectProject(projectId: string): Promise<void> {
    this.selectedProjectId = projectId;
    this.project = null;
    this.roleProviders = {};
    this.roleModels = {};
    this.errorMessage = '';
    if (!projectId) return;
    const response = await this.api.get<Project>(`/api/v1/projects/${encodeURIComponent(projectId)}`);
    if (!response.ok || !response.data) {
      this.errorMessage = `No se pudo cargar el proyecto: ${response.error || 'error del servidor'}`;
      return;
    }
    this.project = response.data;
    for (const role of this.roles) {
      const profile = this.project.agent_profiles?.[role.key];
      const selected = this.catalog?.models.find(model =>
        model.provider_id === profile?.provider_id &&
        model.harness_id === profile?.harness_id &&
        model.canonical_model_id === profile?.model_id
      );
      if (selected) {
        this.roleProviders[role.key] = selected.provider_id;
        this.roleModels[role.key] = selected.id;
      }
    }
  }

  providersFor(role: RoleChoice): string[] {
    return [...new Set(this.modelsForRole(role).map(model => model.provider_id))].sort();
  }

  modelsFor(role: RoleChoice): RegistryModel[] {
    return this.modelsForRole(role).filter(model =>
      !this.roleProviders[role.key] || model.provider_id === this.roleProviders[role.key]
    );
  }

  private modelsForRole(role: RoleChoice): RegistryModel[] {
    const currentId = this.roleModels[role.key];
    return (this.catalog?.models || []).filter(model => {
      const agent = this.agentEntries.find(entry => entry.id === model.harness_id);
      const agentHasModel = Boolean(agent && Object.prototype.hasOwnProperty.call(agent.models || {}, model.canonical_model_id));
      const roleSupported = Boolean(agent && agent.roles.includes(role.agentRole) && (
        role.key === 'independent_review'
          ? agent.read_only_roles.includes(role.agentRole)
          : agent.file_edit_roles.includes(role.agentRole)
      ));
      const modelCompatible = role.capability.every(capability => model.capabilities?.[capability] === true);
      const observed = model.discovery_status === 'available' && model.is_enabled && agentHasModel && roleSupported && modelCompatible;
      return observed || model.id === currentId;
    });
  }

  selectProvider(role: RoleChoice, providerId: string): void {
    this.roleProviders[role.key] = providerId;
    if (!this.modelsFor(role).some(model => model.id === this.roleModels[role.key])) {
      this.roleModels[role.key] = '';
    }
  }

  get hasEditableProfiles(): boolean {
    const profiles = this.project?.agent_profiles || {};
    return Boolean(this.project && ['thinking', 'execution', 'independent_review', 'fallback'].every(key => profiles[key]));
  }

  async saveRoleAssignments(): Promise<void> {
    if (!this.project || !this.hasEditableProfiles) return;
    const profiles = structuredClone(this.project.agent_profiles || {});
    for (const role of this.roles) {
      const selected = this.catalog?.models.find(model => model.id === this.roleModels[role.key]);
      if (!selected || !selected.is_enabled || selected.discovery_status !== 'available') {
        this.errorMessage = `Selecciona un modelo habilitado y disponible para ${role.label}.`;
        return;
      }
      const current = profiles[role.key];
      profiles[role.key] = {
        ...current,
        agent_id: selected.harness_id,
        provider_id: selected.provider_id,
        harness_id: selected.harness_id,
        model_id: selected.canonical_model_id,
        route: typeof selected.capabilities?.['model_route'] === 'string'
          ? selected.capabilities['model_route'] as string
          : current.route
      };
    }
    this.savingRoles = true;
    this.errorMessage = '';
    this.successMessage = '';
    const response = await this.api.patch<Project>(
      `/api/v1/projects/${encodeURIComponent(this.project.project_id)}`,
      { agent_profiles: profiles }
    );
    if (response.ok && response.data) {
      this.project = response.data;
      this.successMessage = 'Asignaciones guardadas y confirmadas por el servidor.';
    } else {
      this.errorMessage = `No se pudieron guardar las asignaciones: ${response.error || 'validación rechazada'}`;
    }
    this.savingRoles = false;
  }
}
