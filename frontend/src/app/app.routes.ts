import { Routes } from '@angular/router';
import { DashboardComponent } from './features/dashboard/dashboard.component';
import { TrabajoComponent } from './features/trabajo/trabajo.component';
import { TrabajoActualComponent } from './features/trabajo-actual/trabajo-actual.component';
import { ProyectosComponent } from './features/proyectos/proyectos.component';
import { BacklogComponent } from './features/backlog/backlog.component';

export const routes: Routes = [
  { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
  { path: 'dashboard', component: DashboardComponent },
  { path: 'trabajo', component: TrabajoComponent },
  { path: 'trabajo-actual', component: TrabajoActualComponent },
  { path: 'proyectos', component: ProyectosComponent },
  { path: 'backlog', component: BacklogComponent },
  { path: '**', redirectTo: 'dashboard' }
];
