import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
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

interface HarnessResult {
  harness_id: string;
  status: string;
  code: string;
  summary: string;
}

@Component({
  selector: 'app-admin-models',
  standalone: true,
  imports: [CommonModule],
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

  constructor(private readonly api: ApiService) {}

  async ngOnInit(): Promise<void> {
    const catalogResponse = await this.api.get<ProviderCatalog>('/api/v1/admin/providers/catalog');
    if (!catalogResponse.ok || !catalogResponse.data) {
      this.errorMessage = 'No se pudo cargar el catálogo de proveedores y modelos.';
      return;
    }
    this.catalog = catalogResponse.data;
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
