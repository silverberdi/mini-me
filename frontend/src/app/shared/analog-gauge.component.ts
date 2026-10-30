import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-analog-gauge',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="flex flex-col items-center justify-center p-4 bg-slate-800/60 rounded-xl border border-slate-700/60 shadow-inner">
      <div class="relative w-36 h-20 overflow-hidden flex items-end justify-center">
        <!-- Semi-circle Track -->
        <svg class="w-36 h-36 transform -rotate-180" viewBox="0 0 100 50">
          <path d="M 10 50 A 40 40 0 0 1 90 50" fill="none" stroke="currentColor" class="text-slate-700" stroke-width="8" stroke-linecap="round" />
          <path d="M 10 50 A 40 40 0 0 1 90 50" fill="none" stroke="currentColor" [class]="gaugeColorClass" stroke-width="8" stroke-linecap="round" [style.stroke-dasharray]="dashArray" [style.stroke-dashoffset]="dashOffset" />
        </svg>
        <!-- Needle / Value display -->
        <div class="absolute bottom-0 flex flex-col items-center">
          <span class="text-2xl font-bold tracking-tight text-white">{{ value }}{{ unit }}</span>
        </div>
      </div>
      <div class="mt-2 text-xs font-medium uppercase tracking-wider text-slate-400 text-center">
        {{ label }}
      </div>
      <div *ngIf="sublabel" class="text-[11px] text-slate-500 mt-0.5">
        {{ sublabel }}
      </div>
    </div>
  `
})
export class AnalogGaugeComponent {
  @Input() label: string = '';
  @Input() sublabel?: string = '';
  @Input() value: number = 0;
  @Input() max: number = 100;
  @Input() unit: string = '%';
  @Input() color: 'sky' | 'emerald' | 'amber' | 'rose' = 'sky';

  get percent(): number {
    if (this.max <= 0) return 0;
    const p = (this.value / this.max) * 100;
    return Math.min(100, Math.max(0, p));
  }

  get dashArray(): string {
    // Arc length for r=40 is PI * 40 ~= 125.66
    return '126';
  }

  get dashOffset(): string {
    const total = 126;
    const fraction = this.percent / 100;
    return `${total * (1 - fraction)}`;
  }

  get gaugeColorClass(): string {
    switch (this.color) {
      case 'emerald': return 'text-emerald-500';
      case 'amber': return 'text-amber-500';
      case 'rose': return 'text-rose-500';
      default: return 'text-sky-500';
    }
  }
}
