import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-analog-gauge',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="group relative flex flex-col items-center justify-center p-4 bg-slate-800/60 rounded-xl border border-slate-700/60 shadow-inner hover:border-slate-500/80 transition-all cursor-pointer">
      <!-- Floating Tooltip / Popover -->
      <div *ngIf="sublabel"
           class="pointer-events-none absolute -top-9 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 group-hover:pointer-events-auto transition-all duration-200 z-50 bg-slate-950 text-slate-200 text-xs px-3 py-1.5 rounded-lg border border-slate-700 shadow-xl whitespace-nowrap">
        <span>{{ sublabel }}</span>
        <div class="absolute top-full left-1/2 -translate-x-1/2 -mt-[1px] border-4 border-transparent border-t-slate-700"></div>
      </div>

      <!-- 270-degree Arc SVG Gauge -->
      <div class="relative w-28 h-28 flex items-center justify-center">
        <svg class="w-28 h-28" viewBox="0 0 100 100">
          <!-- Background 270deg Arc Track (open at bottom: M 23.13 76.87 A 38 38 0 1 1 76.87 76.87) -->
          <path
            d="M 23.13 76.87 A 38 38 0 1 1 76.87 76.87"
            fill="none"
            stroke="currentColor"
            class="text-slate-700/60"
            stroke-width="8"
            stroke-linecap="round"
          />
          <!-- Foreground 270deg Progress -->
          <path
            d="M 23.13 76.87 A 38 38 0 1 1 76.87 76.87"
            fill="none"
            stroke="currentColor"
            [class]="gaugeColorClass"
            stroke-width="8"
            stroke-linecap="round"
            stroke-dasharray="179.07 179.07"
            [style.stroke-dashoffset]="dashOffset"
            class="transition-all duration-500 ease-out"
          />
        </svg>

        <!-- Centered Value Display -->
        <div class="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <span class="text-2xl font-bold tracking-tight text-white">{{ value }}{{ unit }}</span>
        </div>
      </div>

      <!-- Minimal Provider Title (Codex, Antigravity, DeepSeek, OpenRouter) -->
      <div class="mt-2 text-xs font-semibold uppercase tracking-wider text-slate-300 text-center">
        {{ label }}
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

  get dashOffset(): number {
    // 270-degree arc of circle r=38: arc length is (270/360) * 2 * PI * 38 = 179.07
    const arcLength = 179.07;
    const fraction = this.percent / 100;
    return arcLength * (1 - fraction);
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
