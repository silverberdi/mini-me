import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router } from '@angular/router';
import { AuthService } from './core/auth.service';
import { RefreshService } from './core/refresh.service';
import { ThemeService } from './core/theme.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, RouterModule],
  template: `
    <!-- Top Global Header -->
    <header class="h-16 border-b border-slate-800 bg-slate-900/80 backdrop-blur-md sticky top-0 z-50 flex items-center justify-between px-4 sm:px-6">
      <div class="flex items-center gap-6">
        <a routerLink="/dashboard" class="flex items-center gap-2.5 text-white font-bold text-lg hover:text-sky-400 transition-colors">
          <span class="w-8 h-8 rounded-lg bg-sky-500/20 border border-sky-500/30 flex items-center justify-center text-sky-400">⚡</span>
          <span>mini me <span class="text-xs font-normal text-slate-400 block -mt-1 uppercase tracking-wider">centro de control</span></span>
        </a>

        <!-- Project Selector Dropdown -->
        <div class="hidden sm:flex items-center gap-2">
          <label for="projectSelector" class="text-xs text-slate-400 font-medium">Proyecto:</label>
          <select id="projectSelector"
                  [value]="refresh.activeProject()?.project_id || ''"
                  (change)="onProjectChange($event)"
                  class="bg-slate-800 border border-slate-700 text-xs rounded-lg px-2.5 py-1.5 text-slate-200 focus:outline-none focus:border-sky-500">
            <option *ngFor="let p of refresh.projects()" [value]="p.project_id">
              {{ p.project_id }} ({{ p.status || 'ACTIVE' }})
            </option>
          </select>
        </div>
      </div>

      <!-- Controls & Session -->
      <div class="flex items-center gap-2 sm:gap-3">
        <!-- Connection Status -->
        <span class="hidden md:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
              [ngClass]="refresh.isConnected() ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'">
          <span class="w-1.5 h-1.5 rounded-full" [ngClass]="refresh.isConnected() ? 'bg-emerald-400 animate-pulse' : 'bg-rose-400'"></span>
          {{ refresh.isConnected() ? 'Conectado' : 'Sin conexión' }}
        </span>

        <!-- Refresh Interval Selector -->
        <label class="hidden lg:flex items-center gap-1.5 text-xs text-slate-400">
          <span>Actualizar</span>
          <select [value]="refresh.interval()" (change)="onIntervalChange($event)"
                  class="bg-slate-800 border border-slate-700 text-xs rounded-lg px-2 py-1 text-slate-200 focus:outline-none focus:border-sky-500">
            <option value="manual">Manual</option>
            <option value="5">5 s</option>
            <option value="10">10 s</option>
            <option value="30">30 s</option>
          </select>
        </label>

        <!-- Refresh Manual Button -->
        <button (click)="refresh.read()"
                [disabled]="refresh.isRefreshing()"
                class="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 transition-colors"
                title="Actualizar ahora" aria-label="Actualizar datos operativos">
          <svg class="w-4 h-4" [ngClass]="{'animate-spin': refresh.isRefreshing()}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
        </button>
        <span *ngIf="refresh.syncState() === 'syncing'" class="text-xs text-sky-300" role="status" aria-live="polite">Sincronizando…</span>

        <!-- Theme Toggle -->
        <button (click)="theme.toggleTheme()"
                class="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 transition-colors"
                title="Cambiar tema">
          <span *ngIf="theme.isDark()">☀️</span>
          <span *ngIf="!theme.isDark()">🌙</span>
        </button>

        <!-- Logout Button -->
        <button (click)="auth.logout()"
                class="px-3 py-1.5 text-xs font-semibold rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 transition-colors">
          Salir
        </button>
      </div>
    </header>

    <!-- Offline Banner -->
    <div *ngIf="!refresh.isConnected()" class="bg-rose-500/20 border-b border-rose-500/30 text-rose-200 text-xs py-2 px-4 text-center" role="status" aria-live="polite">
      Sin conexión con el servidor mini me. Las observaciones retenidas están obsoletas desde {{ refresh.lastUpdated() | date:'HH:mm:ss' }}; no se permiten mutaciones ni se encolan acciones.
    </div>

    <!-- Main Navigation & Content Layout -->
    <div class="flex min-h-[calc(100vh-4rem)]">
      <!-- Sidebar Navigation -->
      <aside class="w-64 border-r border-slate-800 bg-slate-900/50 p-4 hidden md:flex flex-col justify-between">
        <nav class="space-y-1.5" aria-label="Navegación principal">
          <a routerLink="/dashboard" routerLinkActive="bg-sky-500/10 text-sky-400 border-sky-500/30"
             class="flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-medium text-slate-400 hover:text-white hover:bg-slate-800/60 border border-transparent transition-colors">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/></svg>
            Dashboard
          </a>

          <a routerLink="/backlog" routerLinkActive="bg-sky-500/10 text-sky-400 border-sky-500/30"
             class="flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-medium text-slate-400 hover:text-white hover:bg-slate-800/60 border border-transparent transition-colors">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/></svg>
            Backlog
          </a>

          <a routerLink="/trabajo" routerLinkActive="bg-sky-500/10 text-sky-400 border-sky-500/30"
             class="flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-medium text-slate-400 hover:text-white hover:bg-slate-800/60 border border-transparent transition-colors">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/></svg>
            Trabajo
          </a>

          <a routerLink="/trabajo-actual" routerLinkActive="bg-sky-500/10 text-sky-400 border-sky-500/30"
             class="flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-medium text-slate-400 hover:text-white hover:bg-slate-800/60 border border-transparent transition-colors">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
            Trabajo Actual
          </a>

          <a routerLink="/proyectos" routerLinkActive="bg-sky-500/10 text-sky-400 border-sky-500/30"
             class="flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-sm font-medium text-slate-400 hover:text-white hover:bg-slate-800/60 border border-transparent transition-colors">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>
            Proyectos
          </a>
        </nav>

        <div class="p-3 bg-slate-800/40 border border-slate-700/40 rounded-xl text-xs text-slate-400 space-y-1">
          <div class="font-medium text-slate-300">Fase 8: Angular + Tailwind</div>
          <div class="text-[11px] text-slate-500">Contrato Rector v1.3</div>
        </div>
      </aside>

      <!-- Main Content Area -->
      <main class="flex-1 p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto w-full overflow-y-auto">
        <router-outlet></router-outlet>
      </main>
    </div>
  `
})
export class AppComponent implements OnInit {
  constructor(
    public auth: AuthService,
    public refresh: RefreshService,
    public theme: ThemeService,
    private router: Router
  ) {}

  async ngOnInit(): Promise<void> {
    const isAuthed = await this.auth.checkSession();
    if (isAuthed) {
      await this.refresh.read();
    }
  }

  onProjectChange(event: any) {
    const pid = event.target.value;
    if (pid) {
      this.refresh.setSelectedProject(pid);
    }
  }

  onIntervalChange(event: any) {
    this.refresh.setInterval(event.target.value);
  }
}
