import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/api.service';

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

interface WatchdogSettings {
  provider_id: string | null;
  harness_id: string | null;
  canonical_model_id: string | null;
  inactivity_threshold_minutes: number;
  mode: 'diagnostic_only' | 'mechanical_remediation';
  updated_at?: string | null;
}

interface HarnessResult {
  harness_id: string;
  status: string;
  code: string;
  summary: string;
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
          <p class="mt-1 text-sm text-slate-400">Catálogo de proveedores, harnesses instalados y habilitación global de modelos.</p>
        </div>
        <button type="button" (click)="refreshHarnesses()" [disabled]="refreshingHarnesses"
                class="rounded-lg border border-sky-500/30 bg-sky-500/10 px-4 py-2 text-sm font-semibold text-sky-200 disabled:opacity-50 cursor-pointer">
          {{ refreshingHarnesses ? 'Consultando harnesses…' : 'Actualizar estado de harnesses' }}
        </button>
      </header>

      <p *ngIf="errorMessage" role="alert" class="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">{{ errorMessage }}</p>
      <p *ngIf="successMessage" role="status" class="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-200">{{ successMessage }}</p>

      <section aria-labelledby="watchdog-heading" class="space-y-4 rounded-xl border border-slate-700 bg-slate-800/40 p-4 sm:p-5">
        <div>
          <h2 id="watchdog-heading" class="text-lg font-semibold">Watchdog / SRE global</h2>
          <p class="mt-1 text-sm text-slate-400">Configuración transversal de diagnóstico y recuperación mecánica.</p>
        </div>
        <div *ngIf="watchdogSettings" class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <label class="space-y-1 text-sm">
            <span class="block text-slate-300">Proveedor y modelo</span>
            <select [value]="selectedWatchdogModelId" (change)="selectWatchdogModel($any($event.target).value)"
                    class="w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-slate-100">
              <option value="">Sin modelo asignado</option>
              <option *ngFor="let model of availableModels()" [value]="model.id">
                {{ model.provider_id }} / {{ model.canonical_model_id }}
              </option>
            </select>
          </label>
          <label class="space-y-1 text-sm">
            <span class="block text-slate-300">Umbral de inactividad (minutos)</span>
            <input type="number" min="1" step="1" [(ngModel)]="watchdogThresholdMinutes"
                   class="w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-slate-100">
          </label>
          <label class="space-y-1 text-sm">
            <span class="block text-slate-300">Modo</span>
            <select [(ngModel)]="watchdogMode" class="w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-slate-100">
              <option value="diagnostic_only">Solo diagnóstico</option>
              <option value="mechanical_remediation">Auto-remediación mecánica</option>
            </select>
          </label>
        </div>
        <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p *ngIf="watchdogSettings" class="text-xs text-slate-500">
            Guardado: {{ watchdogSettings.provider_id || 'sin modelo' }} · {{ watchdogSettings.inactivity_threshold_minutes }} min · {{ watchdogSettings.mode === 'diagnostic_only' ? 'Solo diagnóstico' : 'Auto-remediación mecánica' }}
          </p>
          <button type="button" (click)="saveWatchdogSettings()" [disabled]="savingWatchdog || !watchdogSettings"
                  class="rounded-lg border border-sky-500/30 bg-sky-500/10 px-4 py-2 text-sm font-semibold text-sky-200 disabled:opacity-50">
            {{ savingWatchdog ? 'Guardando…' : 'Guardar Watchdog' }}
          </button>
        </div>
      </section>

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
              <th class="p-3">Proveedor / modelo</th><th class="p-3">Harness</th><th class="p-3">Descubrimiento</th><th class="p-3">Estado de operador</th>
            </tr></thead>
            <tbody>
              <tr *ngFor="let model of catalog?.models" class="border-t border-slate-800">
                <td class="p-3"><div class="font-medium">{{ model.provider_id }} / {{ model.canonical_model_id }}</div><div class="text-xs text-slate-500">{{ model.origin }}</div></td>
                <td class="p-3">{{ model.harness_id }}</td>
                <td class="p-3"><span>{{ model.discovery_status }}</span><span *ngIf="model.diagnostic?.summary" class="mt-1 block max-w-sm text-xs text-slate-400">{{ model.diagnostic?.summary }}</span></td>
                <td class="p-3">
                  <label class="inline-flex items-center gap-2 cursor-pointer" [attr.aria-label]="(model.is_enabled ? 'Deshabilitar ' : 'Habilitar ') + model.canonical_model_id">
                    <input type="checkbox" [checked]="model.is_enabled" [disabled]="busyModelId === model.id" (change)="toggleModel(model, $event)" class="h-4 w-4 rounded border-slate-600 bg-slate-800 text-sky-500">
                    <span>{{ model.is_enabled ? 'Habilitado' : 'Deshabilitado' }}</span>
                  </label>
                </td>
              </tr>
              <tr *ngIf="!catalog?.models?.length"><td colspan="4" class="p-4 text-center text-slate-400">El catálogo aún no contiene modelos.</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </section>
  `
})
export class AdminModelsComponent implements OnInit {
  catalog: ProviderCatalog | null = null;
  harnessResults: HarnessResult[] | null = null;
  busyModelId: string | null = null;
  refreshingHarnesses = false;
  errorMessage = '';
  successMessage = '';
  watchdogSettings: WatchdogSettings | null = null;
  selectedWatchdogModelId = '';
  watchdogThresholdMinutes = 15;
  watchdogMode: WatchdogSettings['mode'] = 'diagnostic_only';
  savingWatchdog = false;

  constructor(private readonly api: ApiService) {}

  async ngOnInit(): Promise<void> {
    const [catalogResponse, watchdogResponse] = await Promise.all([
      this.api.get<ProviderCatalog>('/api/v1/admin/providers/catalog'),
      this.api.get<WatchdogSettings>('/api/v1/admin/watchdog/settings')
    ]);
    if (catalogResponse.ok && catalogResponse.data) {
      this.catalog = catalogResponse.data;
    } else {
      this.errorMessage = 'No se pudo cargar el catálogo de proveedores y modelos.';
    }
    if (watchdogResponse.ok && watchdogResponse.data) {
      this.watchdogSettings = watchdogResponse.data;
      this.watchdogThresholdMinutes = watchdogResponse.data.inactivity_threshold_minutes;
      this.watchdogMode = watchdogResponse.data.mode;
      const selected = this.availableModels().find(model =>
        model.provider_id === watchdogResponse.data!.provider_id &&
        model.harness_id === watchdogResponse.data!.harness_id &&
        model.canonical_model_id === watchdogResponse.data!.canonical_model_id
      );
      this.selectedWatchdogModelId = selected?.id || '';
    } else if (!this.errorMessage) {
      this.errorMessage = 'No se pudo cargar la configuración global del Watchdog.';
    }
  }

  availableModels(): RegistryModel[] {
    return (this.catalog?.models || []).filter(model =>
      model.discovery_status === 'available' && model.is_enabled
    );
  }

  selectWatchdogModel(modelId: string): void {
    this.selectedWatchdogModelId = modelId;
  }

  async saveWatchdogSettings(): Promise<void> {
    if (!this.watchdogSettings || this.savingWatchdog) return;
    const selected = this.availableModels().find(model => model.id === this.selectedWatchdogModelId);
    this.savingWatchdog = true;
    this.errorMessage = '';
    this.successMessage = '';
    const response = await this.api.patch<WatchdogSettings>('/api/v1/admin/watchdog/settings', {
      provider_id: selected?.provider_id || null,
      harness_id: selected?.harness_id || null,
      canonical_model_id: selected?.canonical_model_id || null,
      inactivity_threshold_minutes: Number(this.watchdogThresholdMinutes),
      mode: this.watchdogMode
    });
    if (response.ok && response.data) {
      this.watchdogSettings = response.data;
      this.watchdogThresholdMinutes = response.data.inactivity_threshold_minutes;
      this.watchdogMode = response.data.mode;
      this.successMessage = 'La configuración global del Watchdog quedó guardada.';
    } else {
      this.errorMessage = `No se pudo guardar Watchdog: ${response.error || 'error del servidor'}`;
    }
    this.savingWatchdog = false;
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
}
