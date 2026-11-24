import { CommonModule } from '@angular/common';
import { Component, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/api.service';
import { RefreshService } from '../../core/refresh.service';

interface WatchdogSuggestion {
  id: string;
  project_id: string;
  run_id: string;
  change_name: string;
  stage: string;
  candidate_sha: string | null;
  status: string;
  root_cause: string;
  affected_component: string;
  summary: string;
  evidence: Record<string, unknown>;
  improvement_suggestion: string | null;
  suggestion_status: 'pending' | 'converted' | 'discarded';
  created_at: string;
}

@Component({
  selector: 'app-mejora-continua',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <main class="mx-auto max-w-6xl space-y-6 text-slate-100">
      <header>
        <h1 class="text-2xl font-bold">Mejora Continua</h1>
        <p class="mt-1 text-sm text-slate-400">Sugerencias observadas por Watchdog; no se crean Issues automáticamente.</p>
      </header>
      <div class="flex flex-wrap gap-3 rounded-xl border border-slate-700 bg-slate-800/40 p-4">
        <label class="text-sm text-slate-300">Proyecto
          <select [(ngModel)]="projectFilter" (change)="load()" class="ml-2 rounded border border-slate-600 bg-slate-900 px-2 py-1">
            <option value="">Todos</option>
            <option *ngFor="let project of refresh.projects()" [value]="project.project_id">{{ project.project_id }}</option>
          </select>
        </label>
        <label class="text-sm text-slate-300">Estado
          <select [(ngModel)]="statusFilter" (change)="load()" class="ml-2 rounded border border-slate-600 bg-slate-900 px-2 py-1">
            <option value="">Todos</option><option value="pending">Pendiente</option>
            <option value="converted">Copiada como borrador</option><option value="discarded">Descartada</option>
          </select>
        </label>
      </div>
      <p *ngIf="message()" role="status" class="rounded-lg border border-sky-500/30 bg-sky-500/10 p-3 text-sm text-sky-100">{{ message() }}</p>
      <p *ngIf="error()" role="alert" class="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-100">{{ error() }}</p>
      <section *ngIf="recurrenceEntries().length" aria-label="Patrones observados" class="rounded-xl border border-slate-700 bg-slate-800/30 p-4">
        <h2 class="font-semibold">Patrones observados</h2>
        <ul class="mt-2 flex flex-wrap gap-3 text-sm text-slate-300">
          <li *ngFor="let pattern of recurrenceEntries()">{{ pattern[0] }} · {{ pattern[1] }} casos</li>
        </ul>
      </section>
      <section *ngIf="items().length" class="grid gap-4 lg:grid-cols-2">
        <article *ngFor="let item of items()" class="space-y-3 rounded-xl border border-slate-700 bg-slate-800/40 p-5">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <h2 class="font-semibold">{{ item.root_cause }} · {{ item.stage }}</h2>
            <span class="rounded-full bg-slate-700 px-2 py-1 text-xs">{{ statusLabel(item.suggestion_status) }}</span>
          </div>
          <p class="text-sm text-slate-300">{{ item.summary }}</p>
          <p class="text-xs text-slate-400">Componente: {{ item.affected_component }}</p>
          <p class="whitespace-pre-wrap rounded-lg bg-slate-900/70 p-3 text-sm text-slate-200">{{ item.improvement_suggestion }}</p>
          <div class="text-xs text-slate-400">{{ item.project_id }} · {{ item.change_name }} · Run {{ item.run_id }} · {{ item.created_at | date:'medium' }}</div>
          <div *ngIf="item.suggestion_status === 'pending'" class="flex gap-2">
            <button type="button" (click)="copy(item)" class="rounded-lg bg-sky-500 px-3 py-2 text-sm font-semibold text-slate-950">Copiar borrador</button>
            <button type="button" (click)="discard(item)" class="rounded-lg border border-slate-600 px-3 py-2 text-sm">Descartar</button>
          </div>
        </article>
      </section>
      <div *ngIf="!items().length && !loading()" class="rounded-xl border border-slate-700 bg-slate-800/30 p-10 text-center text-sm text-slate-400">No hay sugerencias para estos filtros.</div>
    </main>
  `
})
export class MejoraContinuaComponent implements OnInit {
  readonly items = signal<WatchdogSuggestion[]>([]);
  readonly recurrences = signal<Record<string, number>>({});
  readonly message = signal('');
  readonly error = signal('');
  readonly loading = signal(false);
  projectFilter = '';
  statusFilter: '' | WatchdogSuggestion['suggestion_status'] = '';

  constructor(private readonly api: ApiService, public readonly refresh: RefreshService) {}

  ngOnInit(): void { void this.load(); }

  async load(): Promise<void> {
    this.loading.set(true);
    this.error.set('');
    const query = new URLSearchParams();
    if (this.projectFilter) query.set('project_id', this.projectFilter);
    if (this.statusFilter) query.set('status_filter', this.statusFilter);
    const response = await this.api.get<{ items: WatchdogSuggestion[]; recurrences: Record<string, number> }>(`/api/v1/admin/watchdog/diagnoses?${query}`);
    if (response.ok && response.data) {
      this.items.set(response.data.items || []);
      this.recurrences.set(response.data.recurrences || {});
    }
    else this.error.set(`No se pudo cargar el feed: ${response.error || 'error del servidor'}`);
    this.loading.set(false);
  }

  statusLabel(status: WatchdogSuggestion['suggestion_status']): string {
    return status === 'converted' ? 'Copiada como borrador' : status === 'discarded' ? 'Descartada' : 'Pendiente';
  }

  recurrenceEntries(): Array<[string, number]> { return Object.entries(this.recurrences()); }

  async copy(item: WatchdogSuggestion): Promise<void> {
    this.message.set('');
    this.error.set('');
    const draft = `Título: Mejora detectada en ${item.root_cause}\n\nContexto: ${item.project_id} / ${item.change_name} / ${item.stage}\nRun: ${item.run_id}\n\n${item.improvement_suggestion || item.summary}\n\nEvidencia observada: ${JSON.stringify(item.evidence, null, 2)}`;
    try {
      await navigator.clipboard.writeText(draft);
    } catch {
      this.error.set('El navegador no permitió copiar. La sugerencia sigue pendiente.');
      return;
    }
    await this.setStatus(item, 'converted');
    if (!this.error()) this.message.set('Borrador copiado. No se creó ni modificó ningún Issue.');
  }

  async discard(item: WatchdogSuggestion): Promise<void> { await this.setStatus(item, 'discarded'); }

  private async setStatus(item: WatchdogSuggestion, status: 'converted' | 'discarded'): Promise<void> {
    const response = await this.api.patch<WatchdogSuggestion>(`/api/v1/admin/watchdog/diagnoses/${encodeURIComponent(item.id)}/suggestion`, { status });
    if (!response.ok || !response.data) {
      this.error.set(`No se pudo guardar el estado: ${response.error || 'error del servidor'}`);
      return;
    }
    this.items.update(items => items.map(candidate => candidate.id === item.id ? response.data! : candidate));
  }
}
