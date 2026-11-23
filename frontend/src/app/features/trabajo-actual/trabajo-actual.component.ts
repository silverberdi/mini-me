import { Component, computed, effect, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, ActivatedRoute } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { RefreshService } from '../../core/refresh.service';
import { ApiService } from '../../core/api.service';
import {
  getStageBadgeClass,
  getStageIllustrationPath,
  getStagePanelClass,
  PIPELINE_STAGES,
} from '../../shared/pipeline-stage-presentation';

@Component({
  selector: 'app-trabajo-actual',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule],
  template: `
    <div class="space-y-6">
      <!-- Header -->
      <div class="grid gap-0 bg-slate-800/40 p-2 rounded-2xl border border-slate-700/50 backdrop-blur-sm md:grid-cols-[minmax(0,1fr)_minmax(8rem,10rem)] md:items-center">
        <div class="min-w-0">
          <h1 class="text-2xl font-bold tracking-tight text-white flex items-center gap-3">
            <span>Trabajo Actual</span>
            <span *ngIf="targetRun()" class="text-xs font-mono font-bold px-2.5 py-1 rounded-md bg-sky-500/10 text-sky-400 border border-sky-500/20">
              {{ targetRun()?.run_id }}
            </span>
          </h1>
          <p class="text-sm text-slate-400 mt-1">Supervisión detallada de la ejecución, avance de fases y resolución de atención humana.</p>
          <a routerLink="/trabajo" data-testid="back-to-work" class="mt-1 inline-flex max-w-full shrink-0 items-center gap-1.5 whitespace-nowrap px-3.5 py-1 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-slate-300 transition-colors">
            <span>&larr;</span>
            <span>Volver a Trabajo</span>
          </a>
        </div>
        <div *ngIf="stageIllustrationPath() as illustrationPath" class="flex h-16 min-w-0 items-center justify-center md:h-20" data-testid="stage-illustration-slot">
          <img [src]="illustrationPath" alt="" data-testid="stage-illustration" class="h-full w-full object-contain object-center" />
        </div>
      </div>

      <div *ngIf="cancellationMessage()" class="p-4 rounded-xl text-sm"
           [ngClass]="cancellationSuccess() ? 'bg-emerald-500/10 border border-emerald-500/30 text-emerald-200' : 'bg-rose-500/10 border border-rose-500/30 text-rose-200'"
           role="status" aria-live="polite" data-testid="run-cancellation-result">
        {{ cancellationMessage() }}
      </div>

      <!-- No Run Available State -->
      <div *ngIf="!targetRun()" class="bg-slate-800/30 rounded-2xl border border-slate-700/40 p-12 text-center">
        <div class="w-12 h-12 rounded-full bg-slate-800 flex items-center justify-center mx-auto mb-4 text-slate-500 text-xl">
          ⚙️
        </div>
        <h3 class="text-base font-semibold text-slate-300">No hay un Run disponible para supervisión</h3>
        <p class="text-sm text-slate-500 mt-1 max-w-sm mx-auto">
          El Run solicitado no fue expuesto o no existe una ejecución activa en el proyecto seleccionado.
        </p>
      </div>

      <!-- Run Content -->
      <div *ngIf="targetRun()" class="space-y-6">
        <!-- Main Run Header -->
        <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 p-6 backdrop-blur-sm">
          <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <div class="flex items-center gap-3 flex-wrap">
                <span class="font-mono text-sm font-bold text-white">{{ targetRun()?.run_id }}</span>
                <span class="px-2.5 py-1 text-xs font-semibold rounded-lg"
                      [ngClass]="{
                        'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20': targetRun()?.status === 'SUCCEEDED' || targetRun()?.status === 'COMPLETED',
                        'bg-sky-500/10 text-sky-400 border border-sky-500/20': targetRun()?.status === 'RUNNING' || targetRun()?.status === 'IN_PROGRESS',
                        'bg-rose-500/10 text-rose-400 border border-rose-500/20': targetRun()?.status === 'FAILED' || targetRun()?.status === 'ERRORED',
                        'bg-amber-500/10 text-amber-400 border border-amber-500/20': targetRun()?.status === 'PAUSED' || targetRun()?.status === 'WAITING' || isHumanRequired()
                      }">
                  {{ targetRun()?.status }}
                </span>
                <span *ngIf="targetRun()?.is_active" class="px-2 py-0.5 text-[11px] font-semibold rounded-full bg-sky-500/20 text-sky-300 border border-sky-500/30">
                  Activo
                </span>
              </div>
              <h2 class="text-lg font-bold text-white mt-2">{{ targetRun()?.change_name || 'Sin cambio OpenSpec asignado' }}</h2>
              <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-400 font-mono mt-1">
                <span>Proyecto: <strong class="text-slate-300">{{ targetRun()?.project_id }}</strong></span>
                <span>Request: <strong class="text-slate-300">{{ targetRun()?.request_id || 'N/A' }}</strong></span>
                <span>Inicio: <strong class="text-slate-300">{{ targetRun()?.created_at || 'N/A' }}</strong></span>
              </div>
            </div>
            <div class="flex flex-col items-start md:items-end gap-1">
              <span class="text-xs text-slate-400 uppercase font-mono">Etapa Actual</span>
              <span class="px-3 py-1.5 rounded-xl bg-slate-900 border border-slate-700 text-sm font-bold text-sky-400 font-mono">
                {{ targetRun()?.stage }}
              </span>
            </div>
          </div>
        </div>

        <!-- 10-Stage Pipeline Stepper -->
        <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 p-6 backdrop-blur-sm space-y-4">
          <div class="flex items-center justify-between">
            <h2 class="text-sm font-bold text-white uppercase tracking-wider font-mono">Fases del Pipeline de Orquestación</h2>
            <span class="text-xs text-slate-500 font-mono">10 Etapas Verificables</span>
          </div>

          <div class="grid grid-cols-2 sm:grid-cols-5 lg:grid-cols-10 gap-2">
            <div *ngFor="let stage of pipelineStages; let idx = index"
                 class="p-2.5 rounded-xl border flex flex-col items-center text-center transition-all"
                 [ngClass]="getStageClass(stage.key)">
              <span class="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold font-mono mb-1.5"
                    [ngClass]="getBadgeClass(stage.key)">
                {{ idx + 1 }}
              </span>
              <span class="text-[11px] font-semibold leading-tight line-clamp-2">
                {{ stage.label }}
              </span>
            </div>
          </div>

          <div class="text-xs text-slate-400 font-mono pt-2 border-t border-slate-800 flex items-center justify-between">
            <span>Etapa actual observada: <strong class="text-sky-400">{{ targetRun()?.stage || 'UNKNOWN' }}</strong></span>
            <span>Salidas y evidencias vinculadas a SHA duradero</span>
          </div>

          <div *ngIf="activeApplyCycle() as cycle" class="p-3 rounded-xl bg-slate-900/70 border border-sky-500/20 text-xs font-mono text-slate-300" role="status" aria-label="Ciclo activo de Apply">
            Ciclo de Apply: <strong class="text-white">{{ cycle.attempts }}/{{ cycle.hard_limit }}</strong>
            <span class="text-slate-500"> · Sin progreso: {{ cycle.no_progress }}/{{ cycle.no_progress_limit }}</span>
          </div>

          <div *ngIf="targetRun()?.stop_details?.['apply_gate_update'] as update" class="p-3 rounded-xl bg-slate-900/70 border border-amber-500/20 text-xs text-slate-300 space-y-1" role="status" aria-label="Resultado de actualización OpenSpec del gate Apply">
            <div>Decisión del gate → OpenSpec Update: <strong class="text-white">{{ update.status }}</strong>
              <span *ngIf="update.validation?.status"> · Validación estricta: {{ update.validation.status }}</span>
            </div>
            <div *ngIf="update.error || update.question" class="text-amber-200 whitespace-pre-wrap">{{ update.error || update.question }}</div>
            <div *ngIf="update.deferred_tasks?.length" class="text-slate-400">
              Diferidas y aún pendientes: {{ update.deferred_task_details?.join(' · ') || update.deferred_tasks.join(', ') }}
            </div>
            <div *ngIf="update.before?.candidate_sha || update.after?.candidate_sha" class="font-mono text-slate-500">
              Candidato antes: {{ update.before?.candidate_sha || 'desconocido' }} · después: {{ update.after?.candidate_sha || 'sin cambio registrado' }}
            </div>
          </div>

          <div class="p-4 rounded-xl bg-slate-900/60 border border-slate-700/50 space-y-2" aria-label="Complejidad asignada">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <span class="text-xs font-semibold uppercase tracking-wider text-slate-300 font-mono">Complejidad asignada</span>
              <span class="px-2.5 py-1 rounded-lg bg-slate-800 border border-slate-700 text-xs font-bold text-sky-300 font-mono">
                {{ assignedComplexity() }}
              </span>
            </div>
            <p *ngIf="complexityEvidence()" class="text-xs text-slate-300 whitespace-pre-wrap">
              <strong class="text-slate-400">Evidencia:</strong> {{ complexityEvidence() }}
            </p>
            <p *ngIf="isHighComplexity()" class="text-xs text-amber-200" role="status">
              La complejidad alta requiere revisión de propuesta y revisión de código; esta indicación no confirma que esas revisiones ya hayan ocurrido.
            </p>
          </div>
        </div>

        <div *ngIf="isGateResponsePending()" class="p-4 rounded-xl bg-sky-500/10 border border-sky-500/30 text-sm text-sky-200" role="status" aria-live="polite">
          {{ submissionMessage() || 'Respuesta enviada, procesando…' }}
        </div>

        <!-- HUMAN_REQUIRED Interactive Attention Gate -->
        <div *ngIf="isHumanRequired()" class="p-6 rounded-2xl bg-amber-500/10 border-2 border-amber-500/40 space-y-4 shadow-xl">
          <div class="flex items-start gap-3">
            <div class="w-10 h-10 rounded-xl bg-amber-500/20 text-amber-300 flex items-center justify-center text-2xl shrink-0">
              ⚠️
            </div>
            <div>
              <h3 class="text-base font-bold text-white">Atención Humana Requerida (HUMAN_REQUIRED)</h3>
              <p class="text-xs text-slate-300 mt-1">
                El workflow se encuentra detenido a la espera de una aclaración o decisión explícita del operador para continuar.
              </p>
            </div>
          </div>

          <!-- Question Prompt -->
          <div class="p-4 rounded-xl bg-slate-900/90 border border-amber-500/30 space-y-2">
            <span class="text-xs font-semibold uppercase tracking-wider text-amber-400 font-mono">Pregunta del Workflow:</span>
            <p class="text-sm text-slate-100 font-medium whitespace-pre-wrap">{{ humanGateQuestion() }}</p>
            <p *ngIf="humanGateDescription() && humanGateDescription() !== humanGateQuestion()" class="text-sm text-slate-200 whitespace-pre-wrap">
              <strong>Descripción:</strong> {{ humanGateDescription() }}
            </p>
            <p *ngIf="humanGateOriginalQuestion()" class="text-xs text-slate-400 whitespace-pre-wrap">
              <strong>Texto original:</strong> {{ humanGateOriginalQuestion() }}
            </p>
          </div>

          <!-- Spanish Actionable Explanation (if available) -->
          <div *ngIf="humanGateExplanationEs()" class="p-4 rounded-xl bg-slate-900/90 border border-sky-500/30 space-y-2">
            <span class="text-xs font-semibold uppercase tracking-wider text-sky-400 font-mono">Contexto Explicativo (Español):</span>
            <p class="text-sm text-slate-100 font-medium whitespace-pre-wrap">{{ humanGateExplanationEs() }}</p>
          </div>

          <!-- Apply Diagnostic Context (if available) -->
          <div *ngIf="humanGateAttempts() !== null" class="p-4 rounded-xl bg-slate-900/80 border border-slate-700/60 space-y-2 text-xs font-mono">
            <span class="text-xs font-semibold uppercase tracking-wider text-slate-300">Diagnóstico de Implementación (Apply):</span>
            <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 text-slate-300">
              <div>Intentos: <strong class="text-white">{{ humanGateAttempts() }}/{{ humanGateHardLimit() || 3 }}</strong></div>
              <div>Sin progreso: <strong class="text-white">{{ humanGateNoProgress() || 0 }}</strong></div>
              <div>Pruebas: <strong [ngClass]="humanGateTestsPassed() ? 'text-emerald-400' : humanGateTestsPassed() === false ? 'text-rose-400' : 'text-slate-400'">{{ humanGateTestsPassed() ? 'Aprobadas' : humanGateTestsPassed() === false ? 'Fallidas' : 'Sin ejecutar' }}</strong></div>
              <div>Candidate: <strong class="text-slate-200 truncate max-w-[120px]">{{ humanGateCandidateSha() || 'N/A' }}</strong></div>
            </div>
            <div *ngIf="humanGatePendingTasks().length > 0" class="pt-2 text-slate-400">
              <span>Tareas pendientes: </span>
              <span class="text-amber-300 font-semibold">{{ humanGatePendingTasks().join(', ') }}</span>
            </div>
            <div *ngIf="!humanGateLogsAvailable()" class="text-slate-500 italic pt-1">
              * Los registros detallados de ejecución no están disponibles en el resumen durable.
            </div>
          </div>

          <div *ngIf="humanGateFindings().length > 0" class="space-y-3" aria-label="Hallazgos de la revisión independiente">
            <section *ngFor="let finding of humanGateFindings(); let i = index" class="p-4 rounded-xl bg-slate-900/70 border border-amber-500/20 space-y-2">
              <h4 class="text-xs font-bold uppercase tracking-wider text-amber-300">Hallazgo {{ i + 1 }}</h4>
              <p class="text-sm text-slate-200">La revisión marcó un hallazgo {{ humanGateSeverityLabel(finding.severity) }} en {{ finding.location || 'una ubicación no indicada' }}.</p>
              <p *ngIf="finding.violated_requirement" class="text-sm text-slate-200"><strong>Requisito en riesgo:</strong> {{ finding.violated_requirement }}. Si no se corrige, la propuesta seguirá sin cumplirlo.</p>
              <p *ngIf="finding.expected_correction" class="text-sm text-slate-200"><strong>Corrección que pide el reviewer:</strong> {{ finding.expected_correction }}</p>
            </section>
            <div *ngIf="humanGateReviewerSummary()" class="text-xs text-slate-400 whitespace-pre-wrap">
              <strong>Resumen original del reviewer:</strong> {{ humanGateReviewerSummary() }}
            </div>
          </div>

          <section *ngIf="humanGateAffectedItems().length > 0" class="space-y-2" aria-label="Elementos afectados">
            <h4 class="text-xs font-semibold uppercase tracking-wider text-slate-300">Elementos afectados</h4>
            <ul class="list-disc pl-5 text-sm text-slate-200 space-y-1">
              <li *ngFor="let item of humanGateAffectedItems()">{{ humanGateAffectedItemLabel(item) }}</li>
            </ul>
          </section>
          <section *ngIf="humanGateDiff()" class="space-y-2" aria-label="Diferencias del gate">
            <h4 class="text-xs font-semibold uppercase tracking-wider text-slate-300">Diferencias</h4>
            <pre class="p-3 rounded-xl bg-slate-900/80 border border-slate-700 text-xs text-slate-200 whitespace-pre-wrap overflow-x-auto">{{ humanGateDiff() }}</pre>
          </section>

          <!-- Options (if available) -->
          <div *ngIf="humanGateOptions().length > 0" class="space-y-2">
            <span class="text-xs font-semibold text-slate-300 font-mono">
              {{ humanGateOptionsSource() === 'system_generated' ? 'Sugerencia del sistema; puedes responder con otro texto:' : humanGateOptionsSource() === 'native' ? 'Opciones originales del workflow:' : 'Opciones para responder a este gate:' }}
            </span>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <button *ngFor="let opt of humanGateOptions(); let i = index"
                      type="button"
                      (click)="selectHumanGateOption(opt)"
                      class="p-3 text-left rounded-xl bg-slate-900/60 hover:bg-slate-800 border border-slate-700 hover:border-sky-500 transition-colors cursor-pointer group">
                <div class="text-xs font-bold text-white group-hover:text-sky-300">{{ humanGateOptionLabel(opt, i) }}</div>
                <div *ngIf="humanGateOptionOriginalLabel(opt, i)" class="text-[11px] text-slate-400 mt-1 whitespace-pre-wrap">
                  <strong>Texto original:</strong> {{ humanGateOptionOriginalLabel(opt, i) }}
                </div>
                <div *ngIf="opt.source === 'system_generated'" class="text-[10px] uppercase tracking-wide text-sky-300 mt-1">Sugerencia del sistema</div>
                <div *ngIf="opt.description" class="text-[11px] text-slate-400 mt-0.5">{{ opt.description }}</div>
                <div *ngIf="humanGateOptionExplanation(opt, i)" class="text-[11px] text-slate-300 mt-1 whitespace-pre-wrap">
                  {{ humanGateOptionExplanation(opt, i) }}
                </div>
              </button>
            </div>
          </div>

          <!-- Response Form -->
          <form (submit)="submitHumanResponse($event)" class="space-y-3 pt-2">
            <div>
              <label for="clarificationInput" class="block text-xs font-medium text-slate-300 mb-1">
                Respuesta explícita del operador:
              </label>
              <textarea
                id="clarificationInput"
                rows="4"
                [ngModel]="operatorResponse()"
                (ngModelChange)="operatorResponse.set($event)"
                name="operatorResponse"
                placeholder="Escribe la respuesta, aclaración u opción seleccionada para continuar la ejecución..."
                required
                class="w-full bg-slate-950 border border-slate-700 rounded-xl p-3 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500">
              </textarea>
            </div>

            <div class="flex items-center justify-between">
              <span class="text-xs text-slate-400 font-mono">La respuesta se envía a la autoridad duradera del backend.</span>
              <button
                type="submit"
                [disabled]="isSubmitting() || !operatorResponse().trim()"
                class="px-5 py-2.5 rounded-xl bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white font-semibold text-xs tracking-wide shadow-lg transition-all flex items-center gap-2 cursor-pointer">
                <span *ngIf="isSubmitting()" class="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
                <span>{{ isSubmitting() ? 'Enviando…' : 'Enviar respuesta y continuar' }}</span>
              </button>
            </div>

            <div *ngIf="submissionMessage()"
                 class="p-3 rounded-xl text-xs font-mono"
                 [ngClass]="submissionSuccess() ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'">
              {{ submissionMessage() }}
            </div>
          </form>

          <section *ngIf="canCancelHumanRun()" class="pt-3 border-t border-amber-500/20 space-y-3" aria-label="Cancelar Run">
            <p class="text-xs text-slate-300">Cancelar termina este Run y libera el espacio del proyecto. No reanuda Apply ni marca el Issue como completado.</p>
            <label for="runCancellationReason" class="block text-xs font-medium text-slate-300">Motivo de cancelación:</label>
            <input id="runCancellationReason" type="text" maxlength="500"
                   [ngModel]="cancellationReason()" (ngModelChange)="cancellationReason.set($event)"
                   name="cancellationReason" class="w-full bg-slate-950 border border-slate-700 rounded-xl p-3 text-sm text-slate-100"
                   placeholder="Explica por qué se detiene este Run" />
            <button type="button" data-testid="cancel-run"
                    (click)="cancelHumanRun()"
                    [disabled]="isCancelling() || !cancellationReason().trim()"
                    class="px-4 py-2 rounded-xl border border-rose-500/40 text-rose-200 hover:bg-rose-500/10 disabled:opacity-50 text-xs font-semibold">
              {{ isCancelling() ? 'Cancelando…' : 'Cancelar Run' }}
            </button>
          </section>
        </div>

        <!-- Normal State Gate Banner (when not human required) -->
        <div *ngIf="!isHumanRequired() && !isGateResponsePending()" class="p-4 rounded-xl bg-slate-800/40 border border-slate-700/50 flex items-center justify-between text-xs text-slate-400">
          <span class="flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-emerald-400"></span>
            <span>No existe bloqueo de atención humana activo. El workflow avanza de forma autónoma.</span>
          </span>
          <span class="font-mono text-slate-500">WAITING_CAPACITY / UNKNOWN no generan preguntas.</span>
        </div>

        <!-- Independent code review recovery -->
        <div *ngIf="canRecoverCodeReview()" class="p-6 rounded-2xl bg-violet-500/10 border-2 border-violet-500/30 space-y-4 shadow-xl">
          <div class="flex items-start gap-3">
            <div class="w-10 h-10 rounded-xl bg-violet-500/20 text-violet-300 flex items-center justify-center text-2xl shrink-0">🔍</div>
            <div>
              <h3 class="text-base font-bold text-white">Revisión independiente pendiente</h3>
              <p class="text-xs text-slate-300 mt-1">
                El intento anterior no produjo un veredicto estructurado. Puedes autorizar una repetición sobre el mismo Run y candidato.
              </p>
            </div>
          </div>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs font-mono text-slate-400">
            <span>Intento: <strong class="text-slate-200">{{ codeReviewAttemptId() }}</strong></span>
            <span>Candidate SHA: <strong class="text-slate-200">{{ codeReviewCandidateSha() }}</strong></span>
          </div>
          <div class="flex items-center justify-between gap-3">
            <span class="text-xs text-slate-400">El backend rechazará autorizaciones obsoletas o repetidas.</span>
            <button type="button" (click)="recoverCodeReview()" [disabled]="isRecoveringCodeReview()"
                    class="px-5 py-2.5 rounded-xl bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white font-semibold text-xs tracking-wide shadow-lg transition-all flex items-center gap-2 cursor-pointer">
              <span *ngIf="isRecoveringCodeReview()" class="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
              <span>{{ isRecoveringCodeReview() ? 'Reanudando…' : 'Repetir revisión independiente' }}</span>
            </button>
          </div>
          <div *ngIf="codeReviewRecoveryMessage()" class="p-3 rounded-xl text-xs font-mono"
               [ngClass]="codeReviewRecoverySuccess() ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'">
            {{ codeReviewRecoveryMessage() }}
          </div>
        </div>

        <!-- Independent proposal review recovery -->
        <div *ngIf="canRecoverProposalReview()" class="p-6 rounded-2xl bg-amber-500/10 border-2 border-amber-500/30 space-y-4 shadow-xl">
          <div class="flex items-start gap-3">
            <div class="w-10 h-10 rounded-xl bg-amber-500/20 text-amber-300 flex items-center justify-center text-2xl shrink-0">📋</div>
            <div>
              <h3 class="text-base font-bold text-white">Revisión de propuesta pendiente</h3>
              <p class="text-xs text-slate-300 mt-1">
                El intento anterior de revisión de propuesta no produjo un veredicto estructurado. Puedes autorizar una repetición sobre el mismo Run y candidato.
              </p>
            </div>
          </div>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs font-mono text-slate-400">
            <span>Intento: <strong class="text-slate-200">{{ proposalReviewAttemptId() }}</strong></span>
          </div>
          <div class="flex items-center justify-between gap-3">
            <span class="text-xs text-slate-400">El backend rechazará autorizaciones obsoletas o repetidas.</span>
            <button type="button" (click)="recoverProposalReview()" [disabled]="isRecoveringProposalReview()"
                    class="px-5 py-2.5 rounded-xl bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white font-semibold text-xs tracking-wide shadow-lg transition-all flex items-center gap-2 cursor-pointer">
              <span *ngIf="isRecoveringProposalReview()" class="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
              <span>{{ isRecoveringProposalReview() ? 'Reanudando…' : 'Repetir revisión de propuesta' }}</span>
            </button>
          </div>
          <div *ngIf="proposalReviewRecoveryMessage()" class="p-3 rounded-xl text-xs font-mono"
               [ngClass]="proposalReviewRecoverySuccess() ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'">
            {{ proposalReviewRecoveryMessage() }}
          </div>
        </div>

        <section *ngIf="canRecoverNativeStage()" class="p-5 rounded-2xl bg-amber-500/10 border border-amber-500/30 space-y-3" role="status" data-testid="native-stage-recovery">
          <h3 class="text-sm font-bold text-white">Recuperación de {{ nativeRecoveryStageLabel() }}</h3>
          <p class="text-sm text-slate-200">{{ nativeRecoveryHold()?.['reason'] }}</p>
          <p class="text-xs text-slate-400">{{ nativeRecoveryHold()?.['action'] }}</p>
          <button type="button" (click)="recoverNativeStage()" [disabled]="isRecoveringNativeStage()"
                  class="px-4 py-2 rounded-xl bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-xs font-semibold">
            {{ isRecoveringNativeStage() ? 'Autorizando…' : 'Autorizar y reanudar este Run' }}
          </button>
          <p *ngIf="nativeRecoveryMessage()" [ngClass]="nativeRecoverySuccess() ? 'text-emerald-300' : 'text-rose-300'"
             class="text-xs" aria-live="polite">{{ nativeRecoveryMessage() }}</p>
        </section>

        <!-- Technical Identity & Evidence Grid -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 p-6 backdrop-blur-sm space-y-4">
            <h3 class="text-base font-semibold text-white">Identidad & Control de Versiones</h3>
            <div class="space-y-3 text-xs font-mono">
              <div class="flex justify-between py-2 border-b border-slate-700/40">
                <span class="text-slate-400 font-sans">Run ID:</span>
                <span class="text-slate-200 font-bold">{{ targetRun()?.run_id }}</span>
              </div>
              <div class="flex justify-between py-2 border-b border-slate-700/40">
                <span class="text-slate-400 font-sans">Base SHA:</span>
                <span class="text-slate-300 truncate max-w-[200px]">{{ targetRun()?.base_sha || 'No disponible' }}</span>
              </div>
              <div class="flex justify-between py-2 border-b border-slate-700/40">
                <span class="text-slate-400 font-sans">Candidate SHA:</span>
                <span class="text-slate-300 truncate max-w-[200px]">{{ targetRun()?.candidate_sha || targetRun()?.current_candidate_sha || 'Pendiente de generación' }}</span>
              </div>
              <div class="flex justify-between py-2 border-b border-slate-700/40">
                <span class="text-slate-400 font-sans">Agente Ejecutor:</span>
                <span class="text-slate-200">{{ targetRun()?.active_agent_id || 'Autónomo / Ninguno' }}</span>
              </div>
            </div>
          </div>

          <div class="bg-slate-800/40 rounded-2xl border border-slate-700/50 p-6 backdrop-blur-sm space-y-4">
            <h3 class="text-base font-semibold text-white">Diagnóstico & Supervisión</h3>
            <div *ngIf="targetRun()?.error_detail" class="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs font-mono whitespace-pre-wrap">
              {{ targetRun()?.error_detail }}
            </div>
            <div *ngIf="isHumanRequired()" class="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs space-y-1.5">
              <div class="text-amber-400 font-semibold">⚠️ Intervención humana requerida</div>
              <p>El orquestador está en espera de la respuesta del operador para continuar la ejecución.</p>
            </div>
            <div *ngIf="!targetRun()?.error_detail && !isHumanRequired()" class="p-4 rounded-xl bg-slate-900/60 border border-slate-700/40 text-slate-400 text-xs space-y-1.5">
              <div class="text-emerald-400 font-semibold">✓ Sin anomalías reportadas</div>
              <p>El orquestador no ha emitido errores fatales de ejecución para este run.</p>
            </div>
            <div class="text-xs text-slate-500 font-mono">
              Última actualización: {{ targetRun()?.updated_at || 'Reciente' }}
            </div>
          </div>
        </div>
      </div>
    </div>
  `
})
export class TrabajoActualComponent {
  private route = inject(ActivatedRoute);
  private api = inject(ApiService);
  public refresh = inject(RefreshService);

  readonly operatorResponse = signal<string>('');
  readonly isSubmitting = signal<boolean>(false);
  readonly submissionMessage = signal<string | null>(null);
  readonly submissionSuccess = signal<boolean>(false);
  readonly pendingGateAcknowledgement = signal<{ runId: string; identity: string } | null>(null);
  readonly isRecoveringCodeReview = signal<boolean>(false);
  readonly codeReviewRecoveryMessage = signal<string | null>(null);
  readonly codeReviewRecoverySuccess = signal<boolean>(false);
  readonly isRecoveringProposalReview = signal<boolean>(false);
  readonly proposalReviewRecoveryMessage = signal<string | null>(null);
  readonly proposalReviewRecoverySuccess = signal<boolean>(false);
  readonly isRecoveringNativeStage = signal<boolean>(false);
  readonly nativeRecoveryMessage = signal<string | null>(null);
  readonly nativeRecoverySuccess = signal<boolean>(false);
  readonly cancellationReason = signal<string>('');
  readonly isCancelling = signal<boolean>(false);
  readonly cancellationMessage = signal<string | null>(null);
  readonly cancellationSuccess = signal<boolean>(false);

  readonly pipelineStages = PIPELINE_STAGES;

  readonly targetRun = computed(() => {
    const runs = this.refresh.runs();
    const queryRunId = this.route.snapshot.queryParamMap.get('run');
    if (queryRunId) {
      const found = runs.find(r => r.run_id === queryRunId);
      if (found) return found;
    }
    // Default only to current work; historical runs require explicit selection.
    return runs.find(r => r.is_active) || null;
  });

  stageIllustrationPath(): string | null {
    const stage = this.targetRun()?.stage;
    return getStageIllustrationPath(stage);
  }

  assignedComplexity(): 'high' | 'moderate' | 'low' | 'Pendiente' {
    const complexity = this.targetRun()?.stop_details?.['complexity'];
    return complexity === 'high' || complexity === 'moderate' || complexity === 'low'
      ? complexity
      : 'Pendiente';
  }

  complexityEvidence(): string | null {
    const evidence = this.targetRun()?.stop_details?.['complexity_evidence'];
    if (evidence === null || evidence === undefined || evidence === '') return null;
    if (typeof evidence === 'string') return evidence;
    try {
      return JSON.stringify(evidence);
    } catch {
      return null;
    }
  }

  isHighComplexity(): boolean {
    return this.targetRun()?.stop_details?.['complexity'] === 'high';
  }

  constructor() {
    effect(() => {
      const pending = this.pendingGateAcknowledgement();
      if (!pending) return;

      const run = this.refresh.runs().find(candidate => candidate.run_id === pending.runId);
      if (!run || !this.hasHumanGate(run) || this.humanGateIdentity(run) !== pending.identity) {
        this.pendingGateAcknowledgement.set(null);
        this.submissionMessage.set(null);
        this.submissionSuccess.set(false);
      }
    });
  }

  private hasHumanGate(run: any): boolean {
    const status = String(run.status || '').toUpperCase();
    if (['COMPLETED', 'SUCCEEDED', 'FAILED', 'CANCELLED'].includes(status) || run.stage === 'COMPLETED') {
      return false;
    }
    const gate = run.human_gate || run.status;
    return gate === 'HUMAN_REQUIRED' || gate === 'NEEDS_HUMAN' || !!run.stop_details?.['human_payload'];
  }

  private humanGateIdentity(run: any): string {
    const payload = run.stop_details?.['human_payload'] || {};
    return JSON.stringify(Object.keys(payload).length > 0 ? payload : {
      gate: run.human_gate || run.status,
      stage: run.stage,
      question: '',
      options: [],
    });
  }

  private async humanResponseIdempotencyKey(run: any, answer: string): Promise<string> {
    const source = `${run.run_id}:${this.humanGateIdentity(run)}:${answer.trim()}`;
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(source));
    const hex = Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('');
    return `gate-response-${hex}`;
  }

  isGateResponsePending(): boolean {
    const pending = this.pendingGateAcknowledgement();
    const run = this.targetRun();
    return !!pending && !!run && pending.runId === run.run_id && this.hasHumanGate(run)
      && this.humanGateIdentity(run) === pending.identity;
  }

  isHumanRequired(): boolean {
    const run = this.targetRun();
    if (!run) return false;
    if (this.isGateResponsePending()) return false;
    return this.hasHumanGate(run);
  }

  canCancelHumanRun(): boolean {
    const run = this.targetRun();
    return !!run && !!run.is_active && this.isHumanRequired() && !run.active_job_id;
  }

  async cancelHumanRun(): Promise<void> {
    const run = this.targetRun();
    const reason = this.cancellationReason().trim();
    if (!run || !this.canCancelHumanRun() || !reason || this.isCancelling()) return;
    const confirmed = window.confirm(
      `¿Cancelar el Run ${run.run_id}? Se liberará el proyecto; el Run no se completará.`
    );
    if (!confirmed) return;

    this.isCancelling.set(true);
    this.cancellationSuccess.set(false);
    this.cancellationMessage.set('Cancelando Run…');
    try {
      const response = await this.api.post<any>(
        `/api/v1/projects/${encodeURIComponent(run.project_id)}/runs/${encodeURIComponent(run.run_id)}/cancel`,
        {
          reason,
          idempotency_key: `cancel-run-${crypto.randomUUID()}`,
        }
      );
      if (!response.ok || !response.data) {
        this.cancellationMessage.set(`No se canceló el Run: ${response.error || 'respuesta inválida del servidor'}`);
        return;
      }
      this.cancellationSuccess.set(true);
      this.cancellationMessage.set(
        response.data.workspace_cleanup === 'PENDING'
          ? 'Run cancelado y proyecto liberado. La limpieza del worktree quedó pendiente de verificación.'
          : 'Run cancelado y proyecto liberado.'
      );
      await this.refresh.read();
    } catch (error: any) {
      this.cancellationMessage.set(`No se canceló el Run: ${error?.message || 'error de comunicación'}`);
    } finally {
      this.isCancelling.set(false);
    }
  }

  private codeReviewDetails(): Record<string, any> | null {
    const value = this.targetRun()?.stop_details?.['code_review'];
    return value && typeof value === 'object' ? value : null;
  }

  canRecoverCodeReview(): boolean {
    const run = this.targetRun();
    const details = this.codeReviewDetails();
    const reviewStatus = String(details?.['status'] || '').toLowerCase();
    return !!run?.is_active
      && run.stage === 'CODE_REVIEW'
      && !!details?.['attempt_id']
      && !!(details?.['candidate_sha'] || run.candidate_sha || run.current_candidate_sha)
      && ['invalid_response', 'technical_failure', 'provider_error', 'failed', 'error'].includes(reviewStatus);
  }

  codeReviewAttemptId(): string {
    return String(this.codeReviewDetails()?.['attempt_id'] || 'N/A');
  }

  codeReviewCandidateSha(): string {
    const run = this.targetRun();
    return String(this.codeReviewDetails()?.['candidate_sha'] || run?.candidate_sha || run?.current_candidate_sha || 'N/A');
  }

  async recoverCodeReview(): Promise<void> {
    const run = this.targetRun();
    const details = this.codeReviewDetails();
    if (!run || !details?.['attempt_id'] || !this.canRecoverCodeReview() || this.isRecoveringCodeReview()) return;

    this.isRecoveringCodeReview.set(true);
    this.codeReviewRecoveryMessage.set(null);
    try {
      const authorization = await this.api.post<{ action_request_id: string }>(
        `/api/v1/projects/${encodeURIComponent(run.project_id)}/runs/${encodeURIComponent(run.run_id)}/code-review-recovery-authorizations`,
        { prior_attempt_id: details['attempt_id'] }
      );
      if (!authorization.ok || !authorization.data?.action_request_id) {
        throw new Error(authorization.error || 'La autorización de recuperación fue rechazada');
      }

      const resumed = await this.api.post(
        `/api/v1/projects/${encodeURIComponent(run.project_id)}/requests/run`,
        {
          target_run_id: run.run_id,
          code_review_recovery_authorization_id: authorization.data.action_request_id
        }
      );
      if (!resumed.ok) throw new Error(resumed.error || 'No se pudo reanudar el Run');

      this.codeReviewRecoverySuccess.set(true);
      this.codeReviewRecoveryMessage.set('Revisión autorizada. El mismo Run fue reanudado con el revisor independiente; actualizando…');
      await this.refresh.refreshRuns();
    } catch (error: any) {
      this.codeReviewRecoverySuccess.set(false);
      this.codeReviewRecoveryMessage.set(error?.message || 'No se pudo recuperar la revisión');
      await this.refresh.refreshRuns();
    } finally {
      this.isRecoveringCodeReview.set(false);
    }
  }

  private proposalReviewDetails(): Record<string, any> | null {
    const value = this.targetRun()?.stop_details?.['proposal_review'];
    return value && typeof value === 'object' ? value : null;
  }

  canRecoverProposalReview(): boolean {
    const run = this.targetRun();
    const details = this.proposalReviewDetails();
    const reviewStatus = String(details?.['status'] || '').toLowerCase();
    return !!run?.is_active
      && run.stage === 'PROPOSAL_REVIEW'
      && !!details?.['attempt_id']
      && ['invalid_response', 'provider_error', 'failed', 'error'].includes(reviewStatus);
  }

  proposalReviewAttemptId(): string {
    return String(this.proposalReviewDetails()?.['attempt_id'] || 'N/A');
  }

  async recoverProposalReview(): Promise<void> {
    const run = this.targetRun();
    const details = this.proposalReviewDetails();
    if (!run || !details?.['attempt_id'] || !this.canRecoverProposalReview() || this.isRecoveringProposalReview()) return;

    this.isRecoveringProposalReview.set(true);
    this.proposalReviewRecoveryMessage.set(null);
    try {
      const authorization = await this.api.post<{ action_request_id: string }>(
        `/api/v1/projects/${encodeURIComponent(run.project_id)}/runs/${encodeURIComponent(run.run_id)}/proposal-review-recovery-authorizations`,
        { prior_attempt_id: details['attempt_id'] }
      );
      if (!authorization.ok || !authorization.data?.action_request_id) {
        throw new Error(authorization.error || 'La autorización de recuperación fue rechazada');
      }

      const resumed = await this.api.post(
        `/api/v1/projects/${encodeURIComponent(run.project_id)}/requests/run`,
        {
          target_run_id: run.run_id,
          proposal_review_recovery_authorization_id: authorization.data.action_request_id
        }
      );
      if (!resumed.ok) throw new Error(resumed.error || 'No se pudo reanudar el Run');

      this.proposalReviewRecoverySuccess.set(true);
      this.proposalReviewRecoveryMessage.set('Revisión de propuesta autorizada. El mismo Run fue reanudado con el revisor independiente; actualizando…');
      await this.refresh.refreshRuns();
    } catch (error: any) {
      this.proposalReviewRecoverySuccess.set(false);
      this.proposalReviewRecoveryMessage.set(error?.message || 'No se pudo recuperar la revisión de propuesta');
      await this.refresh.refreshRuns();
    } finally {
      this.isRecoveringProposalReview.set(false);
    }
  }

  nativeRecoveryHold(): Record<string, any> | null {
    const hold = this.targetRun()?.stop_details?.['recovery_hold'];
    return hold && typeof hold === 'object' ? hold : null;
  }

  canRecoverNativeStage(): boolean {
    const run = this.targetRun();
    const stage = this.nativeRecoveryHold()?.['stage'];
    return !!run?.is_active && (stage === 'explore' || stage === 'propose')
      && run.stage === (stage === 'explore' ? 'EXPLORING' : 'PROPOSING');
  }

  nativeRecoveryStageLabel(): string {
    return this.nativeRecoveryHold()?.['stage'] === 'explore' ? 'Explore' : 'Propose';
  }

  async recoverNativeStage(): Promise<void> {
    const run = this.targetRun();
    const hold = this.nativeRecoveryHold();
    const stage = hold?.['stage'];
    if (!run || !this.canRecoverNativeStage() || this.isRecoveringNativeStage()) return;
    this.isRecoveringNativeStage.set(true);
    this.nativeRecoveryMessage.set(null);
    try {
      const endpoint = stage === 'explore' ? 'explore' : 'propose';
      const authorization = await this.api.post<{ action_request_id: string }>(
        `/api/v1/projects/${encodeURIComponent(run.project_id)}/runs/${encodeURIComponent(run.run_id)}/${endpoint}-recovery-authorizations`,
        { prior_attempt_id: hold?.['attempt_id'] || null }
      );
      if (!authorization.ok || !authorization.data?.action_request_id) {
        throw new Error(authorization.error || `No se autorizó la recuperación de ${endpoint}`);
      }
      const resumed = await this.api.post(
        `/api/v1/projects/${encodeURIComponent(run.project_id)}/requests/run`,
        { target_run_id: run.run_id, [`${endpoint}_recovery_authorization_id`]: authorization.data.action_request_id }
      );
      if (!resumed.ok) throw new Error(resumed.error || 'No se pudo reanudar el Run');
      this.nativeRecoverySuccess.set(true);
      this.nativeRecoveryMessage.set(`Autorización de ${endpoint} registrada; se reanuda el mismo Run.`);
      await this.refresh.refreshRuns();
    } catch (error: any) {
      this.nativeRecoverySuccess.set(false);
      this.nativeRecoveryMessage.set(error?.message || 'No se pudo recuperar la etapa');
      await this.refresh.refreshRuns();
    } finally {
      this.isRecoveringNativeStage.set(false);
    }
  }

  humanGateQuestion(): string {
    const run = this.targetRun();
    if (!run) return '';
    const payload = run.stop_details?.['human_payload'];
    return payload?.question_es || 'La pregunta del workflow aún no tiene una presentación en español.';
  }

  humanGateDescription(): string {
    const payload = this.targetRun()?.stop_details?.['human_payload'];
    return typeof payload?.description === 'string' ? payload.description : '';
  }

  humanGateOriginalQuestion(): string {
    const run = this.targetRun();
    if (!run) return '';
    const payload = run.stop_details?.['human_payload'];
    const original = payload?.question || payload?.prompt || '';
    return original && original !== this.humanGateQuestion() ? original : '';
  }

  humanGateOptions(): any[] {
    const run = this.targetRun();
    if (!run) return [];
    const payload = run.stop_details?.['human_payload'];
    return Array.isArray(payload?.options) ? payload.options : [];
  }

  humanGateOptionLabel(option: any, index: number): string {
    const run = this.targetRun();
    const payload = run?.stop_details?.['human_payload'];
    const translated = payload?.options_es?.[index] || option?.label_es;
    return typeof translated === 'string' && translated.trim()
      ? translated
      : 'Esta opción todavía no tiene una presentación en español.';
  }

  humanGateOptionOriginalLabel(option: any, index: number): string {
    const run = this.targetRun();
    const payload = run?.stop_details?.['human_payload'];
    const original = typeof option === 'string'
      ? option
      : option?.label || option?.id || option?.response_text || '';
    return original && original !== this.humanGateOptionLabel(option, index) ? original : '';
  }

  selectHumanGateOption(option: any): void {
    const responseText = typeof option?.response_text === 'string' ? option.response_text : '';
    this.operatorResponse.set(responseText || option?.label || option?.id || option || '');
  }

  humanGateFindings(): any[] {
    const run = this.targetRun();
    if (!run) return [];
    const payload = run.stop_details?.['human_payload'];
    return Array.isArray(payload?.review_findings) ? payload.review_findings : [];
  }

  humanGateAffectedItems(): any[] {
    const payload = this.targetRun()?.stop_details?.['human_payload'];
    return Array.isArray(payload?.affected_items) ? payload.affected_items : [];
  }

  humanGateAffectedItemLabel(item: any): string {
    if (typeof item === 'string') return item;
    if (!item || typeof item !== 'object') return String(item ?? '');
    return [item.id, item.title, item.name, item.description]
      .find(value => typeof value === 'string' && value.trim()) || JSON.stringify(item);
  }

  humanGateDiff(): string {
    const diff = this.targetRun()?.stop_details?.['human_payload']?.diff;
    if (typeof diff === 'string') return diff;
    if (!diff || typeof diff !== 'object') return '';
    if (diff.status === 'NOT_APPLICABLE') {
      return typeof diff.description === 'string' ? `No aplica: ${diff.description}` : 'No aplica un diff de tareas o requisitos.';
    }
    if (diff.status === 'UNAVAILABLE') {
      return typeof diff.description === 'string' ? diff.description : 'No se pudo observar el diff de los artefactos implicados.';
    }
    const summary = JSON.stringify({
      status: diff.status,
      tasks: diff.tasks,
      scenarios: diff.scenarios,
    }, null, 2);
    return typeof diff.text === 'string' && diff.text
      ? `${diff.text}\n\nEvidencia de identidad:\n${summary}`
      : `No se pudo observar el diff textual. Evidencia disponible:\n${summary}`;
  }

  humanGateOptionExplanation(option: any, index: number): string {
    const explanations = this.targetRun()?.stop_details?.['human_payload']?.option_explanations;
    const value = Array.isArray(explanations)
      ? explanations[index]
      : explanations && typeof explanations === 'object'
        ? explanations[option?.id || option?.response_text || index]
        : undefined;
    if (typeof value === 'string') return value;
    if (value && typeof value === 'object') {
      return [value.explanation, value.consequence, value.description]
        .find(item => typeof item === 'string' && item.trim()) || '';
    }
    return '';
  }

  humanGateReviewerSummary(): string {
    const run = this.targetRun();
    if (!run) return '';
    const payload = run.stop_details?.['human_payload'];
    return typeof payload?.reviewer_summary === 'string' ? payload.reviewer_summary : '';
  }

  humanGateOptionsSource(): string {
    const run = this.targetRun();
    if (!run) return '';
    const payload = run.stop_details?.['human_payload'];
    return typeof payload?.options_source === 'string' ? payload.options_source : '';
  }

  humanGateExplanationEs(): string {
    const run = this.targetRun();
    if (!run) return '';
    const payload = run.stop_details?.['human_payload'];
    const expl = payload?.explanation_es || payload?.explanation || run.stop_details?.['explanation_es'];
    return typeof expl === 'string' ? expl : '';
  }

  humanGateAttempts(): number | null {
    const run = this.targetRun();
    if (!run) return null;
    const payload = run.stop_details?.['human_payload'];
    return typeof payload?.attempts === 'number' ? payload.attempts : null;
  }

  activeApplyCycle(): { attempts: number; hard_limit: number; no_progress: number; no_progress_limit: number } | null {
    const cycle = this.targetRun()?.['apply_cycle'];
    return cycle && typeof cycle.attempts === 'number' && typeof cycle.hard_limit === 'number'
      ? cycle
      : null;
  }

  humanGateHardLimit(): number | null {
    const run = this.targetRun();
    if (!run) return null;
    const payload = run.stop_details?.['human_payload'];
    return typeof payload?.hard_limit === 'number' ? payload.hard_limit : null;
  }

  humanGateNoProgress(): number | null {
    const run = this.targetRun();
    if (!run) return null;
    const payload = run.stop_details?.['human_payload'];
    return typeof payload?.no_progress === 'number' ? payload.no_progress : null;
  }

  humanGatePendingTasks(): string[] {
    const run = this.targetRun();
    if (!run) return [];
    const payload = run.stop_details?.['human_payload'];
    return Array.isArray(payload?.pending_tasks) ? payload.pending_tasks : [];
  }

  humanGateCandidateSha(): string {
    const run = this.targetRun();
    if (!run) return '';
    const payload = run.stop_details?.['human_payload'];
    return typeof payload?.candidate_sha === 'string' ? payload.candidate_sha : '';
  }

  humanGateTestsPassed(): boolean | null {
    const run = this.targetRun();
    if (!run) return null;
    const payload = run.stop_details?.['human_payload'];
    return typeof payload?.tests_passed === 'boolean' ? payload.tests_passed : null;
  }

  humanGateLogsAvailable(): boolean {
    const run = this.targetRun();
    if (!run) return true;
    const payload = run.stop_details?.['human_payload'];
    return payload?.logs_available !== false;
  }

  humanGateSeverityLabel(severity: unknown): string {
    switch (String(severity || '').toUpperCase()) {
      case 'BLOCKER': return 'bloqueante';
      case 'MAJOR': return 'importante';
      case 'MINOR': return 'menor';
      default: return 'sin severidad indicada';
    }
  }

  getStageClass(stageKey: string): string {
    return getStagePanelClass(stageKey, this.targetRun()?.stage);
  }

  getBadgeClass(stageKey: string): string {
    return getStageBadgeClass(stageKey, this.targetRun()?.stage);
  }

  async submitHumanResponse(event: Event): Promise<void> {
    event.preventDefault();
    const run = this.targetRun();
    const answer = this.operatorResponse().trim();
    if (!run || !answer) return;

    const gateIdentity = this.humanGateIdentity(run);
    this.pendingGateAcknowledgement.set({ runId: run.run_id, identity: gateIdentity });
    this.isSubmitting.set(true);
    this.submissionSuccess.set(false);
    this.submissionMessage.set('Enviando respuesta…');

    try {
      const idempotencyKey = await this.humanResponseIdempotencyKey(run, answer);
      const response = await this.api.post(
        `/api/v1/projects/${encodeURIComponent(run.project_id)}/requests/run`,
        { operator_clarification: answer, idempotency_key: idempotencyKey }
      );

      if (response.ok) {
        this.submissionSuccess.set(true);
        this.submissionMessage.set(run.stage === 'DOC_CLOSING'
          ? 'Respuesta aceptada. DOC_CLOSING queda pendiente del Scheduler; el Run aún no confirma que haya comenzado.'
          : 'Respuesta aceptada. Esperando la actualización del Run para confirmar la siguiente etapa.');
        this.operatorResponse.set('');
        await this.refresh.refreshRuns();
      } else {
        this.pendingGateAcknowledgement.set(null);
        this.submissionSuccess.set(false);
        this.submissionMessage.set(`Error al confirmar respuesta: ${response.error || 'Error no especificado'}`);
      }
    } catch (e: any) {
      this.pendingGateAcknowledgement.set(null);
      this.submissionSuccess.set(false);
      this.submissionMessage.set(`Error de comunicación: ${e.message || e}`);
    } finally {
      this.isSubmitting.set(false);
    }
  }
}
