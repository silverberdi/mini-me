import { CommonModule } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/api.service';
import { RefreshService } from '../../core/refresh.service';

interface MCPCapability {
  kind: string;
  name: string;
  description: string;
  observed_at?: string;
}

interface MCPConnection {
  id: string;
  name: string;
  endpoint: string;
  transport: string;
  auth_type: string;
  status: string;
  diagnostic?: { code: string; summary: string } | null;
  capabilities: MCPCapability[];
  access_token_expires_at?: string | null;
}

interface Preset {
  id: string;
  label: string;
  name: string;
  endpoint: string;
  transport: string;
  auth_type: string;
  authEndpoint?: string;
  tokenEndpoint?: string;
  scopes?: string;
}

const PRESETS: Preset[] = [
  {
    id: 'custom',
    label: 'Personalizado (en blanco)',
    name: '',
    endpoint: '',
    transport: 'http',
    auth_type: 'oauth2',
  },
  {
    id: 'stitch',
    label: 'Plantilla: Google Stitch (Diseño y UI)',
    name: 'Google Stitch',
    endpoint: 'https://stitch.googleapis.com/mcp',
    transport: 'http',
    auth_type: 'oauth2',
    authEndpoint: 'https://accounts.google.com/o/oauth2/v2/auth?response_type=code&scope=openid%20email%20profile%20https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fcloud-platform&access_type=offline&prompt=consent',
    tokenEndpoint: 'https://oauth2.googleapis.com/token',
    scopes: 'https://www.googleapis.com/auth/cloud-platform',
  },
];

@Component({
  selector: 'app-mcp-connections',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <section class="space-y-6 text-slate-100" aria-labelledby="mcp-heading">
      <!-- Encabezado principal -->
      <header class="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <div class="flex items-center gap-3">
            <h1 id="mcp-heading" class="text-2xl font-bold tracking-tight text-white">Conexiones MCP e Integraciones</h1>
            <span class="rounded-full bg-sky-500/10 px-2.5 py-0.5 text-xs font-semibold text-sky-400 border border-sky-500/20">
              {{ currentProjectId }}
            </span>
          </div>
          <p class="mt-1 text-sm text-slate-400">
            Administra integraciones de servidores Model Context Protocol observadas. Los secretos se custodian cifrados en el servidor.
          </p>
        </div>
        <button
          type="button"
          (click)="toggleForm()"
          class="inline-flex items-center justify-center gap-2 rounded-lg bg-sky-500 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-sky-400 focus:outline-none focus:ring-2 focus:ring-sky-400"
        >
          <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" [attr.d]="showForm() ? 'M6 18L18 6M6 6l12 12' : 'M12 4v16m8-8H4'" />
          </svg>
          {{ showForm() ? 'Cerrar formulario' : 'Nueva integración MCP' }}
        </button>
      </header>

      <!-- Mensajes globales de estado y alertas -->
      <aside *ngIf="notice" role="status" class="flex items-center justify-between rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm text-emerald-200">
        <div class="flex items-center gap-3">
          <svg class="h-5 w-5 text-emerald-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span>{{ notice }}</span>
        </div>
        <button type="button" (click)="notice = ''" class="text-emerald-400 hover:text-emerald-300">✕</button>
      </aside>

      <p *ngIf="error" role="alert" class="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-200 flex items-start gap-3">
        <svg class="h-5 w-5 text-rose-400 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <span>{{ error }}</span>
      </p>

      <!-- Formulario de Registro / Vinculación -->
      <div *ngIf="showForm()" class="rounded-2xl border border-slate-700 bg-slate-800/60 p-6 shadow-xl backdrop-blur-sm transition-all">
        <div class="flex items-center justify-between border-b border-slate-700 pb-4 mb-5">
          <div>
            <h2 class="text-lg font-semibold text-white">Registrar servidor MCP</h2>
            <p class="text-xs text-slate-400">Configura el protocolo y las credenciales requeridas para autorizar la integración.</p>
          </div>
          <!-- Selector de Plantilla -->
          <div class="flex items-center gap-2">
            <label for="preset-select" class="text-xs text-slate-400">Plantilla:</label>
            <select
              id="preset-select"
              name="presetSelect"
              [(ngModel)]="selectedPreset"
              (change)="applyPreset($event)"
              class="rounded-lg border border-slate-600 bg-slate-900 px-3 py-1.5 text-xs text-slate-200 focus:border-sky-500 focus:outline-none"
            >
              <option *ngFor="let p of presets" [value]="p.id">{{ p.label }}</option>
            </select>
          </div>
        </div>

        <form (ngSubmit)="submit()" class="space-y-4">
          <!-- Parámetros base de conexión -->
          <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <label class="block text-xs font-medium text-slate-300 mb-1">Nombre de la integración *</label>
              <input
                name="name"
                [(ngModel)]="draft.name"
                required
                placeholder="ej. Google Stitch"
                class="w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-sky-500 focus:outline-none"
              >
            </div>
            <div class="sm:col-span-2">
              <label class="block text-xs font-medium text-slate-300 mb-1">Endpoint MCP *</label>
              <input
                name="endpoint"
                [(ngModel)]="draft.endpoint"
                required
                placeholder="https://... o comando ejecutable"
                class="w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-sky-500 focus:outline-none"
              >
            </div>
            <div>
              <label class="block text-xs font-medium text-slate-300 mb-1">Transporte *</label>
              <select
                name="transport"
                [(ngModel)]="draft.transport"
                class="w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none"
              >
                <option value="http">HTTP (SSE / Streamable)</option>
                <option value="sse">Server-Sent Events (SSE)</option>
                <option value="stdio">stdio (Proceso local)</option>
              </select>
            </div>
          </div>

          <!-- Selector de Autenticación -->
          <div class="pt-2">
            <label class="block text-xs font-medium text-slate-300 mb-1">Método de autenticación *</label>
            <div class="grid grid-cols-3 gap-3">
              <label
                class="flex cursor-pointer items-center justify-center rounded-xl border p-3 text-center transition"
                [ngClass]="draft.auth_type === 'oauth2' ? 'border-sky-500 bg-sky-500/10 text-sky-300 font-semibold' : 'border-slate-700 bg-slate-900/40 text-slate-400 hover:border-slate-600'"
              >
                <input type="radio" name="auth_type" value="oauth2" [(ngModel)]="draft.auth_type" class="sr-only">
                OAuth2 (Google / Web)
              </label>
              <label
                class="flex cursor-pointer items-center justify-center rounded-xl border p-3 text-center transition"
                [ngClass]="draft.auth_type === 'api_key' ? 'border-sky-500 bg-sky-500/10 text-sky-300 font-semibold' : 'border-slate-700 bg-slate-900/40 text-slate-400 hover:border-slate-600'"
              >
                <input type="radio" name="auth_type" value="api_key" [(ngModel)]="draft.auth_type" class="sr-only">
                API Key
              </label>
              <label
                class="flex cursor-pointer items-center justify-center rounded-xl border p-3 text-center transition"
                [ngClass]="draft.auth_type === 'bearer' ? 'border-sky-500 bg-sky-500/10 text-sky-300 font-semibold' : 'border-slate-700 bg-slate-900/40 text-slate-400 hover:border-slate-600'"
              >
                <input type="radio" name="auth_type" value="bearer" [(ngModel)]="draft.auth_type" class="sr-only">
                Bearer Token
              </label>
            </div>
          </div>

          <!-- Campos específicos para OAuth2 -->
          <div *ngIf="draft.auth_type === 'oauth2'" class="space-y-4 rounded-xl border border-sky-500/20 bg-sky-950/20 p-5 mt-3">
            <div class="flex items-center justify-between">
              <span class="text-xs font-semibold text-sky-300 uppercase tracking-wider">Configuración OAuth2</span>
              <!-- Helper de Callback URI -->
              <div class="flex items-center gap-2">
                <span class="text-xs text-slate-400">URI de redireccionamiento requerida:</span>
                <code class="rounded bg-slate-900 px-2 py-1 text-xs text-sky-300 border border-slate-700">{{ callbackUrl }}</code>
                <button
                  type="button"
                  (click)="copyCallbackUrl()"
                  class="rounded bg-slate-800 px-2 py-1 text-xs font-medium text-slate-200 hover:bg-slate-700 transition"
                >
                  {{ copied ? '¡Copiado!' : 'Copiar' }}
                </button>
              </div>
            </div>

            <div class="grid gap-4 sm:grid-cols-2">
              <div>
                <label class="block text-xs font-medium text-slate-300 mb-1">ID de cliente (Client ID) *</label>
                <input
                  name="clientId"
                  [(ngModel)]="oauthForm.clientId"
                  required
                  placeholder="ej. 78367...apps.googleusercontent.com"
                  class="w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-sky-500 focus:outline-none"
                >
              </div>
              <div>
                <label class="block text-xs font-medium text-slate-300 mb-1">Secreto de cliente (Client Secret) *</label>
                <div class="relative">
                  <input
                    name="clientSecret"
                    [type]="showSecret ? 'text' : 'password'"
                    [(ngModel)]="oauthForm.clientSecret"
                    required
                    placeholder="GOCSPX-..."
                    class="w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 pr-10 text-sm text-slate-100 placeholder-slate-500 focus:border-sky-500 focus:outline-none"
                  >
                  <button
                    type="button"
                    (click)="showSecret = !showSecret"
                    class="absolute inset-y-0 right-0 flex items-center pr-3 text-slate-400 hover:text-slate-200 text-xs"
                  >
                    {{ showSecret ? 'Ocultar' : 'Ver' }}
                  </button>
                </div>
              </div>
            </div>

            <p class="text-xs text-slate-400">
              Al hacer clic en el botón inferior serás redirigido a la pantalla de consentimiento del proveedor. Tras autorizar, mini-me capturará los tokens y los guardará cifrados con Fernet en la base de datos.
            </p>
          </div>

          <!-- Campos específicos para API Key -->
          <div *ngIf="draft.auth_type === 'api_key'" class="rounded-xl border border-slate-700 bg-slate-900/50 p-5 mt-3 space-y-3">
            <label class="block text-xs font-medium text-slate-300">API Key / Token de Acceso *</label>
            <div class="relative">
              <input
                name="apiKey"
                [type]="showSecret ? 'text' : 'password'"
                [(ngModel)]="staticForm.key"
                required
                placeholder="Pega la API Key aquí"
                class="w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 pr-10 text-sm text-slate-100 placeholder-slate-500 focus:border-sky-500 focus:outline-none"
              >
              <button
                type="button"
                (click)="showSecret = !showSecret"
                class="absolute inset-y-0 right-0 flex items-center pr-3 text-slate-400 hover:text-slate-200 text-xs"
              >
                {{ showSecret ? 'Ocultar' : 'Ver' }}
              </button>
            </div>
            <p class="text-xs text-slate-500">La clave se envía cifrada mediante canal TLS y se almacena bajo clave maestra de servidor.</p>
          </div>

          <!-- Campos específicos para Bearer Token -->
          <div *ngIf="draft.auth_type === 'bearer'" class="rounded-xl border border-slate-700 bg-slate-900/50 p-5 mt-3 space-y-3">
            <label class="block text-xs font-medium text-slate-300">Bearer Token *</label>
            <div class="relative">
              <input
                name="bearerToken"
                [type]="showSecret ? 'text' : 'password'"
                [(ngModel)]="staticForm.token"
                required
                placeholder="Pega el token Bearer aquí"
                class="w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 pr-10 text-sm text-slate-100 placeholder-slate-500 focus:border-sky-500 focus:outline-none"
              >
              <button
                type="button"
                (click)="showSecret = !showSecret"
                class="absolute inset-y-0 right-0 flex items-center pr-3 text-slate-400 hover:text-slate-200 text-xs"
              >
                {{ showSecret ? 'Ocultar' : 'Ver' }}
              </button>
            </div>
          </div>

          <!-- Acciones de formulario -->
          <div class="flex items-center justify-end gap-3 pt-3 border-t border-slate-700">
            <button
              type="button"
              (click)="showForm.set(false)"
              class="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:bg-slate-800 transition"
            >
              Cancelar
            </button>
            <button
              type="submit"
              [disabled]="loading"
              class="inline-flex items-center gap-2 rounded-lg bg-sky-500 px-5 py-2 text-sm font-semibold text-slate-950 transition hover:bg-sky-400 focus:outline-none focus:ring-2 focus:ring-sky-400 disabled:opacity-50"
            >
              <span *ngIf="loading" class="animate-spin text-xs">⏳</span>
              {{ draft.auth_type === 'oauth2' ? 'Iniciar autorización OAuth2 ↗' : 'Registrar y comprobar' }}
            </button>
          </div>
        </form>
      </div>

      <!-- Estado de carga -->
      <p *ngIf="loading && !connections().length" role="status" class="text-sm text-slate-400">
        Cargando integraciones del proyecto...
      </p>

      <!-- Lista de Conexiones Registradas -->
      <div class="grid gap-6">
        <article
          *ngFor="let connection of connections()"
          class="rounded-2xl border border-slate-700/80 bg-slate-800/40 p-6 shadow-md transition-all hover:border-slate-600"
        >
          <!-- Fila superior: Título, estado y acciones principales -->
          <div class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div class="flex items-center gap-3">
                <h2 class="text-lg font-bold text-white">{{ connection.name }}</h2>
                <!-- Badge de Estado -->
                <span
                  class="inline-flex items-center gap-1.5 rounded-full px-3 py-0.5 text-xs font-semibold"
                  [ngClass]="{
                    'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30': connection.status === 'ACTIVE',
                    'bg-amber-500/20 text-amber-300 border border-amber-500/30': connection.status === 'PENDING',
                    'bg-rose-500/20 text-rose-300 border border-rose-500/30': connection.status === 'ERROR'
                  }"
                >
                  <span class="h-1.5 w-1.5 rounded-full" [ngClass]="connection.status === 'ACTIVE' ? 'bg-emerald-400 animate-pulse' : connection.status === 'PENDING' ? 'bg-amber-400' : 'bg-rose-400'"></span>
                  {{ connection.status }}
                </span>
              </div>
              <p class="mt-1 text-xs text-slate-400 font-mono flex items-center gap-2">
                <span>{{ connection.endpoint }}</span>
                <span>•</span>
                <span class="uppercase">{{ connection.transport }}</span>
                <span>•</span>
                <span class="uppercase text-sky-400 font-semibold">{{ connection.auth_type }}</span>
              </p>
            </div>

            <!-- Acciones de integración -->
            <div class="flex flex-wrap items-center gap-2">
              <button
                type="button"
                (click)="healthCheck(connection)"
                [disabled]="actionLoading[connection.id]"
                class="rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800 transition"
                title="Comprobar salud y latencia del servidor MCP"
              >
                Comprobar salud
              </button>
              <button
                type="button"
                (click)="discover(connection)"
                [disabled]="actionLoading[connection.id]"
                class="rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800 transition"
                title="Redescubrir herramientas y recursos"
              >
                Redescubrir
              </button>
              <button
                *ngIf="connection.auth_type === 'oauth2'"
                type="button"
                (click)="renew(connection)"
                [disabled]="actionLoading[connection.id]"
                class="rounded-lg border border-sky-500/30 bg-sky-500/10 px-3 py-1.5 text-xs text-sky-300 hover:bg-sky-500/20 transition"
                title="Renovar token de acceso con refresh token"
              >
                Renovar token
              </button>
              <button
                type="button"
                (click)="revoke(connection)"
                [disabled]="actionLoading[connection.id]"
                class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-1.5 text-xs text-rose-300 hover:bg-rose-500/20 transition"
                title="Revocar credenciales de esta conexión"
              >
                Revocar
              </button>
              <button
                type="button"
                (click)="deleteConnection(connection)"
                [disabled]="actionLoading[connection.id]"
                class="rounded-lg border border-slate-800 px-2.5 py-1.5 text-xs text-slate-500 hover:text-rose-400 transition"
                title="Eliminar registro"
              >
                🗑
              </button>
            </div>
          </div>

          <!-- Diagnóstico de error si existe -->
          <div *ngIf="connection.diagnostic" class="mt-4 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-300">
            <span class="font-semibold uppercase tracking-wider text-rose-400">Diagnóstico:</span> {{ connection.diagnostic.summary }}
          </div>

          <!-- Sección de Capacidades Observadas (Tools / Resources) -->
          <div class="mt-6 border-t border-slate-700/60 pt-4">
            <div class="flex items-center justify-between mb-3">
              <h3 class="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Capacidades observadas ({{ connection.capabilities.length }})
              </h3>
              <!-- Filtro de herramientas -->
              <input
                *ngIf="connection.capabilities.length > 5"
                type="text"
                placeholder="Filtrar herramientas..."
                [(ngModel)]="toolFilters[connection.id]"
                class="rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-sky-500"
              >
            </div>

            <!-- Lista de herramientas en grid -->
            <div *ngIf="connection.capabilities.length; else noCapabilities" class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              <div
                *ngFor="let cap of filteredCapabilities(connection)"
                class="rounded-xl border border-slate-700/60 bg-slate-900/40 p-3 hover:border-slate-600 transition flex flex-col justify-between"
              >
                <div>
                  <div class="flex items-center justify-between gap-2">
                    <span class="font-mono text-xs font-bold text-sky-300 truncate" [title]="cap.name">{{ cap.name }}</span>
                    <span class="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] uppercase font-semibold text-slate-400">{{ cap.kind }}</span>
                  </div>
                  <p class="mt-1 text-xs text-slate-400 line-clamp-2" [title]="cap.description || 'Sin descripción'">
                    {{ cap.description || 'Sin descripción declarada por el servidor' }}
                  </p>
                </div>
                <div class="mt-3 flex items-center justify-between pt-2 border-t border-slate-800">
                  <span class="text-[10px] text-slate-500">{{ cap.observed_at ? (cap.observed_at | date:'shortTime') : '' }}</span>
                  <button
                    type="button"
                    (click)="openInvokeModal(connection, cap)"
                    class="rounded bg-slate-800 px-2 py-1 text-[11px] font-medium text-sky-400 hover:bg-sky-500/20 hover:text-sky-300 transition"
                  >
                    Probar ⚡
                  </button>
                </div>
              </div>
            </div>

            <ng-template #noCapabilities>
              <p class="text-xs text-slate-500 italic py-2">Sin capacidades descubiertas en este servidor MCP.</p>
            </ng-template>
          </div>
        </article>
      </div>

      <!-- Estado vacío -->
      <div *ngIf="!loading && !connections().length" class="rounded-2xl border border-dashed border-slate-700 p-12 text-center">
        <p class="text-sm font-medium text-slate-300">No hay conexiones MCP registradas para este proyecto.</p>
        <p class="mt-1 text-xs text-slate-500">Haz clic en «Nueva integración MCP» para vincular Google Stitch, servidores locales o APIs remotas.</p>
      </div>

      <!-- Modal de Invocación / Prueba de Herramienta -->
      <div *ngIf="invokeModal.open" class="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
        <div class="w-full max-w-2xl rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl space-y-4">
          <div class="flex items-start justify-between border-b border-slate-800 pb-3">
            <div>
              <div class="flex items-center gap-2">
                <span class="rounded bg-sky-500/10 px-2 py-0.5 text-xs font-semibold text-sky-400 border border-sky-500/20">TEST TOOL</span>
                <h3 class="text-base font-bold text-white font-mono">{{ invokeModal.toolName }}</h3>
              </div>
              <p class="text-xs text-slate-400 mt-1">{{ invokeModal.toolDescription }}</p>
            </div>
            <button type="button" (click)="invokeModal.open = false" class="text-slate-400 hover:text-white">✕</button>
          </div>

          <div>
            <label class="block text-xs font-medium text-slate-300 mb-1">Argumentos (JSON) *</label>
            <textarea
              [(ngModel)]="invokeModal.argsJson"
              rows="4"
              class="w-full rounded-lg border border-slate-700 bg-slate-950 p-3 font-mono text-xs text-slate-200 focus:border-sky-500 focus:outline-none"
              placeholder="{}"
            ></textarea>
          </div>

          <div *ngIf="invokeModal.result" class="space-y-1">
            <span class="text-xs font-semibold uppercase tracking-wider text-slate-400">Respuesta:</span>
            <pre class="max-h-60 overflow-auto rounded-lg border border-slate-800 bg-slate-950 p-3 font-mono text-xs text-emerald-400 whitespace-pre-wrap">{{ invokeModal.result }}</pre>
          </div>

          <div class="flex items-center justify-end gap-3 pt-2">
            <button
              type="button"
              (click)="invokeModal.open = false"
              class="rounded-lg border border-slate-700 px-4 py-2 text-xs text-slate-300 hover:bg-slate-800"
            >
              Cerrar
            </button>
            <button
              type="button"
              (click)="executeInvoke()"
              [disabled]="invokeModal.loading"
              class="rounded-lg bg-sky-500 px-4 py-2 text-xs font-semibold text-slate-950 hover:bg-sky-400 disabled:opacity-50"
            >
              {{ invokeModal.loading ? 'Ejecutando…' : 'Ejecutar llamada' }}
            </button>
          </div>
        </div>
      </div>
    </section>
  `
})
export class McpConnectionsComponent implements OnInit {
  connections = signal<MCPConnection[]>([]);
  loading = false;
  error = '';
  notice = '';
  copied = false;
  showForm = signal(false);
  showSecret = false;
  actionLoading: Record<string, boolean> = {};
  toolFilters: Record<string, string> = {};

  presets = PRESETS;

  selectedPreset = 'custom';

  draft = {
    name: '',
    endpoint: '',
    transport: 'http',
    auth_type: 'oauth2',
  };

  oauthForm = {
    clientId: '',
    clientSecret: '',
    authEndpoint: '',
    tokenEndpoint: '',
  };

  staticForm = {
    key: '',
    token: '',
  };

  invokeModal = {
    open: false,
    connectionId: '',
    toolName: '',
    toolDescription: '',
    argsJson: '{}',
    loading: false,
    result: '',
  };

  public readonly refresh = inject(RefreshService);

  constructor(private readonly api: ApiService) {}

  get currentProjectId(): string {
    return this.refresh.activeProject()?.project_id || this.refresh.selectedProjectId() || 'mini-me';
  }

  get callbackUrl(): string {
    const origin = typeof window !== 'undefined' && window.location ? window.location.origin : 'https://mini-me.silverman.pro';
    return `${origin}/api/v1/projects/${encodeURIComponent(this.currentProjectId)}/mcp-connections/oauth/callback`;
  }

  ngOnInit(): void {
    if (typeof window !== 'undefined' && window.location.search.includes('status=connected')) {
      this.notice = '¡Conexión autorizada y activada con éxito!';
    }
    this.load();
  }

  toggleForm(): void {
    const nextState = !this.showForm();
    this.showForm.set(nextState);
    if (nextState) {
      this.resetForm();
    }
  }

  resetForm(): void {
    this.selectedPreset = 'custom';
    this.draft = {
      name: '',
      endpoint: '',
      transport: 'http',
      auth_type: 'oauth2',
    };
    this.oauthForm = {
      clientId: '',
      clientSecret: '',
      authEndpoint: '',
      tokenEndpoint: '',
    };
    this.staticForm = {
      key: '',
      token: '',
    };
    this.error = '';
  }

  applyPreset(event: Event): void {
    const presetId = (event.target as HTMLSelectElement).value;
    this.selectedPreset = presetId;
    const selected = this.presets.find(p => p.id === presetId);
    if (!selected) return;

    this.draft.name = selected.name;
    this.draft.endpoint = selected.endpoint;
    this.draft.transport = selected.transport;
    this.draft.auth_type = selected.auth_type;
    this.oauthForm.authEndpoint = selected.authEndpoint || '';
    this.oauthForm.tokenEndpoint = selected.tokenEndpoint || '';
  }

  async copyCallbackUrl(): Promise<void> {
    try {
      await navigator.clipboard.writeText(this.callbackUrl);
      this.copied = true;
      setTimeout(() => (this.copied = false), 2500);
    } catch {
      // fallback
    }
  }

  filteredCapabilities(connection: MCPConnection): MCPCapability[] {
    const filter = (this.toolFilters[connection.id] || '').toLowerCase().trim();
    if (!filter) return connection.capabilities;
    return connection.capabilities.filter(
      c => c.name.toLowerCase().includes(filter) || (c.description || '').toLowerCase().includes(filter)
    );
  }

  async load(): Promise<void> {
    this.loading = true;
    const response = await this.api.get<{ connections: MCPConnection[] }>(
      '/api/v1/projects/' + encodeURIComponent(this.currentProjectId) + '/mcp-connections'
    );
    this.loading = false;
    if (response.ok) {
      this.connections.set(response.data?.connections || []);
    } else {
      this.error = response.error || 'No se pudo cargar el catálogo de conexiones';
    }
  }

  async submit(): Promise<void> {
    this.error = '';
    this.notice = '';

    if (this.draft.auth_type === 'oauth2') {
      if (!this.oauthForm.clientId.trim() || !this.oauthForm.clientSecret.trim()) {
        this.error = 'Client ID y Client Secret son requeridos para OAuth2.';
        return;
      }
      this.loading = true;
      const payload = {
        name: this.draft.name,
        endpoint: this.draft.endpoint,
        transport: this.draft.transport,
        auth_type: 'oauth2',
        credentials: {
          authorization_endpoint: `${this.oauthForm.authEndpoint}&client_id=${encodeURIComponent(this.oauthForm.clientId.trim())}&redirect_uri=${encodeURIComponent(this.callbackUrl)}`,
          token_endpoint: this.oauthForm.tokenEndpoint,
          client_id: this.oauthForm.clientId.trim(),
          client_secret: this.oauthForm.clientSecret.trim(),
          redirect_uri: this.callbackUrl,
        },
      };

      const response = await this.api.post<{ authorization_url: string }>(
        `/api/v1/projects/${encodeURIComponent(this.currentProjectId)}/mcp-connections/oauth/start`,
        payload
      );
      this.loading = false;

      if (!response.ok || !response.data?.authorization_url) {
        this.error = response.error || 'No se pudo iniciar el flujo de autorización OAuth2';
      } else {
        // Redirigir al consentimiento del proveedor
        window.location.href = response.data.authorization_url;
      }
    } else {
      // API Key o Bearer
      const credentials: Record<string, string> = {};
      if (this.draft.auth_type === 'api_key') {
        if (!this.staticForm.key.trim()) {
          this.error = 'La API Key es requerida.';
          return;
        }
        credentials['key'] = this.staticForm.key.trim();
      } else if (this.draft.auth_type === 'bearer') {
        if (!this.staticForm.token.trim()) {
          this.error = 'El Bearer Token es requerido.';
          return;
        }
        credentials['token'] = this.staticForm.token.trim();
      }

      this.loading = true;
      const response = await this.api.post(
        `/api/v1/projects/${encodeURIComponent(this.currentProjectId)}/mcp-connections`,
        { ...this.draft, credentials }
      );
      this.loading = false;

      if (!response.ok) {
        this.error = response.error || 'No se pudo registrar la integración MCP';
      } else {
        this.notice = `Integración «${this.draft.name}» registrada correctamente.`;
        this.showForm.set(false);
        this.staticForm = { key: '', token: '' };
        await this.load();
      }
    }
  }

  async healthCheck(connection: MCPConnection): Promise<void> {
    this.actionLoading[connection.id] = true;
    this.error = '';
    const res = await this.api.post<{ status: string; diagnostic?: { summary: string } }>(
      `/api/v1/projects/${encodeURIComponent(this.currentProjectId)}/mcp-connections/${connection.id}/health`,
      {}
    );
    this.actionLoading[connection.id] = false;
    if (res.ok) {
      this.notice = `Salud de «${connection.name}»: ${res.data?.status || 'OK'}`;
      await this.load();
    } else {
      this.error = res.error || 'Falló la comprobación de salud';
    }
  }

  async discover(connection: MCPConnection): Promise<void> {
    this.actionLoading[connection.id] = true;
    this.error = '';
    const res = await this.api.post<{ tools: any[]; resources: any[] }>(
      `/api/v1/projects/${encodeURIComponent(this.currentProjectId)}/mcp-connections/${connection.id}/discover`,
      {}
    );
    this.actionLoading[connection.id] = false;
    if (res.ok) {
      this.notice = `Capacidades actualizadas: ${res.data?.tools?.length || 0} herramientas descubiertas.`;
      await this.load();
    } else {
      this.error = res.error || 'Error al redescubrir herramientas';
    }
  }

  async renew(connection: MCPConnection): Promise<void> {
    this.actionLoading[connection.id] = true;
    this.error = '';
    const res = await this.api.post(
      `/api/v1/projects/${encodeURIComponent(this.currentProjectId)}/mcp-connections/${connection.id}/renew`,
      {}
    );
    this.actionLoading[connection.id] = false;
    if (res.ok) {
      this.notice = `Token renovado exitosamente para «${connection.name}».`;
      await this.load();
    } else {
      this.error = res.error || 'No se pudo renovar el token';
    }
  }

  async revoke(connection: MCPConnection): Promise<void> {
    if (!confirm(`¿Deseas revocar las credenciales de «${connection.name}»?`)) return;
    this.actionLoading[connection.id] = true;
    const res = await this.api.post(
      `/api/v1/projects/${encodeURIComponent(this.currentProjectId)}/mcp-connections/${connection.id}/revoke`,
      {}
    );
    this.actionLoading[connection.id] = false;
    if (res.ok) {
      this.notice = `Credenciales de «${connection.name}» revocadas.`;
      await this.load();
    } else {
      this.error = res.error || 'No se pudo revocar';
    }
  }

  async deleteConnection(connection: MCPConnection): Promise<void> {
    if (!confirm(`¿Eliminar definitivamente la conexión «${connection.name}»?`)) return;
    this.actionLoading[connection.id] = true;
    const res = await this.api.delete(
      `/api/v1/projects/${encodeURIComponent(this.currentProjectId)}/mcp-connections/${connection.id}`
    );
    this.actionLoading[connection.id] = false;
    if (res.ok) {
      this.notice = `Conexión eliminada.`;
      await this.load();
    } else {
      this.error = res.error || 'No se pudo eliminar la conexión';
    }
  }

  openInvokeModal(connection: MCPConnection, cap: MCPCapability): void {
    this.invokeModal = {
      open: true,
      connectionId: connection.id,
      toolName: cap.name,
      toolDescription: cap.description,
      argsJson: '{}',
      loading: false,
      result: '',
    };
  }

  async executeInvoke(): Promise<void> {
    let parsedArgs: Record<string, any> = {};
    try {
      parsedArgs = JSON.parse(this.invokeModal.argsJson || '{}');
    } catch {
      alert('Los argumentos deben ser un JSON válido.');
      return;
    }

    this.invokeModal.loading = true;
    this.invokeModal.result = '';
    const res = await this.api.post<any>(
      `/api/v1/projects/${encodeURIComponent(this.currentProjectId)}/mcp-connections/${this.invokeModal.connectionId}/invoke`,
      {
        tool: this.invokeModal.toolName,
        arguments: parsedArgs,
      }
    );
    this.invokeModal.loading = false;
    if (res.ok) {
      this.invokeModal.result = JSON.stringify(res.data, null, 2);
    } else {
      this.invokeModal.result = `Error: ${res.error || 'Fallo en la invocación'}`;
    }
  }
}
