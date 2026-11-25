import { CommonModule } from '@angular/common';
import { Component, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/api.service';

interface MCPConnection { id: string; name: string; endpoint: string; transport: string; auth_type: string; status: string; diagnostic?: { code: string; summary: string } | null; capabilities: Array<{ kind: string; name: string; description: string }>; }

@Component({
  selector: 'app-mcp-connections', standalone: true, imports: [CommonModule, FormsModule],
  template: `
    <section class="space-y-6 text-slate-100" aria-labelledby="mcp-heading">
      <header><h1 id="mcp-heading" class="text-2xl font-bold">Conexiones MCP</h1><p class="mt-1 text-sm text-slate-400">Integraciones observadas para el proyecto activo. Los secretos permanecen en el servidor.</p></header>
      <p *ngIf="error" role="alert" class="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">{{ error }}</p>
      <p *ngIf="loading" role="status" class="text-sm text-slate-400">Cargando integraciones…</p>
      <form class="grid gap-3 rounded-xl border border-slate-700 bg-slate-800/40 p-5 sm:grid-cols-2" (ngSubmit)="register()">
        <input name="name" [(ngModel)]="draft.name" required placeholder="Nombre de integración" aria-label="Nombre de integración" class="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm">
        <input name="endpoint" [(ngModel)]="draft.endpoint" required placeholder="Endpoint MCP" aria-label="Endpoint MCP" class="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm">
        <select name="transport" [(ngModel)]="draft.transport" class="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm"><option value="http">HTTP</option><option value="sse">SSE</option><option value="stdio">stdio</option></select>
        <select name="auth_type" [(ngModel)]="draft.auth_type" class="rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm"><option value="oauth2">OAuth2</option><option value="api_key">API Key</option><option value="bearer">Bearer</option></select>
        <button type="submit" class="rounded-lg bg-sky-500 px-3 py-2 text-sm font-semibold text-slate-950 sm:col-span-2" [disabled]="loading">Registrar y validar</button>
      </form>
      <div class="grid gap-4 lg:grid-cols-2">
        <article *ngFor="let connection of connections()" class="rounded-xl border border-slate-700 bg-slate-800/40 p-5">
          <div class="flex items-start justify-between gap-3"><div><h2 class="font-semibold">{{ connection.name }}</h2><p class="mt-1 text-xs text-slate-500">{{ connection.transport }} · {{ connection.auth_type }}</p></div><span class="rounded-full px-2 py-1 text-xs" [ngClass]="connection.status === 'ACTIVE' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-slate-700 text-slate-300'">{{ connection.status }}</span></div>
          <p *ngIf="connection.diagnostic" class="mt-3 text-sm text-rose-300">{{ connection.diagnostic.summary }}</p>
          <div class="mt-4"><h3 class="text-xs font-semibold uppercase tracking-wide text-slate-400">Capacidades observadas</h3><ul class="mt-2 space-y-1 text-sm text-slate-300"><li *ngFor="let capability of connection.capabilities">{{ capability.kind }}: {{ capability.name }}</li><li *ngIf="!connection.capabilities.length" class="text-slate-500">Sin capacidades descubiertas</li></ul></div>
          <button type="button" class="mt-4 rounded-lg border border-rose-500/30 px-3 py-2 text-sm text-rose-200" (click)="revoke(connection)" [disabled]="loading">Revocar</button>
        </article>
      </div>
      <p *ngIf="!loading && !connections().length" class="rounded-xl border border-dashed border-slate-700 p-6 text-sm text-slate-400">No hay conexiones MCP registradas.</p>
    </section>`
})
export class McpConnectionsComponent implements OnInit {
  connections = signal<MCPConnection[]>([]); loading = false; error = ''; projectId = '';
  draft = { name: '', endpoint: '', transport: 'http', auth_type: 'oauth2', credentials: {} };
  constructor(private readonly api: ApiService) {}
  ngOnInit(): void { this.load(); }
  async load(): Promise<void> { this.loading = true; const response = await this.api.get<{ connections: MCPConnection[] }>('/api/v1/projects/' + encodeURIComponent(this.projectId) + '/mcp-connections'); this.loading = false; if (response.ok) this.connections.set(response.data?.connections || []); else this.error = response.error || 'No se pudo cargar el catálogo'; }
  async register(): Promise<void> { this.error = ''; this.loading = true; const response = await this.api.post('/api/v1/projects/' + encodeURIComponent(this.projectId) + '/mcp-connections', this.draft); this.loading = false; if (!response.ok) this.error = response.error || 'No se pudo registrar'; else { this.draft = { name: '', endpoint: '', transport: 'http', auth_type: 'oauth2', credentials: {} }; await this.load(); } }
  async revoke(connection: MCPConnection): Promise<void> { const response = await this.api.post(`/api/v1/projects/${encodeURIComponent(this.projectId)}/mcp-connections/${connection.id}/revoke`, {}); if (!response.ok) this.error = response.error || 'No se pudo revocar'; else await this.load(); }
}
