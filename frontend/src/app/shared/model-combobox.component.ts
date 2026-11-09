import {
  Component,
  Input,
  Output,
  EventEmitter,
  ElementRef,
  HostListener,
  ViewChild,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

export interface ModelOption {
  id: string;
  label: string;
  agent: string;
  effort: string;
  group: string;
  provider_id: string;
  harness_id: string;
  route?: string;
}

@Component({
  selector: 'app-model-combobox',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="relative w-full" (keydown)="handleKeydown($event)">
      <label *ngIf="label" [for]="inputId" class="block text-slate-400 mb-1 text-[11px] font-medium">
        {{ label }}
      </label>

      <!-- Combobox Trigger Button -->
      <button
        type="button"
        [id]="inputId"
        role="combobox"
        [attr.aria-expanded]="isOpen"
        aria-haspopup="listbox"
        [attr.aria-controls]="listboxId"
        [disabled]="disabled"
        (click)="toggleOpen()"
        class="w-full bg-slate-800 border border-slate-700 hover:border-slate-600 rounded-xl px-2.5 py-2 text-left text-white focus:outline-none focus:border-sky-500 font-mono text-[11px] flex items-center justify-between transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
      >
        <span class="truncate pr-2" [class.text-slate-500]="!selectedModel" [attr.title]="selectedLabel">
          {{ selectedLabel }}
        </span>
        <svg
          class="w-3.5 h-3.5 text-slate-400 shrink-0 transition-transform duration-150"
          [class.rotate-180]="isOpen"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      <!-- Dropdown Popup -->
      <div
        *ngIf="isOpen"
        [id]="listboxId"
        role="listbox"
        class="absolute z-50 left-0 w-max min-w-[360px] max-w-[480px] mt-1 bg-slate-900 border border-slate-700/80 rounded-xl shadow-2xl p-2 max-h-72 overflow-hidden flex flex-col backdrop-blur-md animate-fade-in"
      >
        <!-- Search Input -->
        <div class="relative mb-1.5 shrink-0">
          <input
            #searchInput
            type="text"
            [(ngModel)]="searchQuery"
            (ngModelChange)="onSearchChange()"
            placeholder="Buscar por proveedor o modelo…"
            class="w-full bg-slate-950 border border-slate-800 rounded-lg pl-7 pr-2.5 py-1.5 text-white placeholder-slate-500 focus:outline-none focus:border-sky-500 font-mono text-[11px]"
          />
          <svg
            class="w-3.5 h-3.5 text-slate-500 absolute left-2 top-2 pointer-events-none"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </div>

        <!-- Filtered Options List -->
        <div class="overflow-y-auto flex-1 space-y-0.5 pr-0.5 custom-scrollbar">
          <div
            *ngIf="filteredModels.length === 0"
            class="p-2 text-center text-slate-500 text-[11px] font-mono"
          >
            No se encontraron modelos
          </div>

          <button
            *ngFor="let m of filteredModels; let idx = index"
            type="button"
            role="option"
            [attr.aria-selected]="m.id === modelValue"
            (click)="selectModel(m)"
            (mouseenter)="highlightedIndex = idx"
            [attr.title]="m.label + ' (' + m.group + ')'"
            [ngClass]="{
              'bg-sky-500/20 border-sky-500/30 text-sky-200': idx === highlightedIndex,
              'border-transparent text-slate-300 hover:bg-slate-800/80': idx !== highlightedIndex
            }"
            class="w-full text-left px-2.5 py-1.5 rounded-lg text-[11px] font-mono flex items-center justify-between cursor-pointer border transition-colors"
          >
            <div class="pr-2 min-w-0">
              <span class="font-medium text-slate-200 block truncate" [class.text-sky-300]="m.id === modelValue">
                {{ m.label }}
              </span>
              <span class="block text-[10px] text-slate-400 truncate">
                {{ m.group }}
              </span>
            </div>
            <span *ngIf="m.id === modelValue" class="text-sky-400 shrink-0 text-xs">✓</span>
          </button>
        </div>
      </div>
    </div>
  `,
  styles: [
    `
      .custom-scrollbar::-webkit-scrollbar {
        width: 4px;
      }
      .custom-scrollbar::-webkit-scrollbar-track {
        background: transparent;
      }
      .custom-scrollbar::-webkit-scrollbar-thumb {
        background: #334155;
        border-radius: 2px;
      }
    `,
  ],
})
export class ModelComboboxComponent {
  @Input() label: string = '';
  @Input() inputId: string = 'model-combobox-' + Math.random().toString(36).substring(2, 9);
  @Input() modelValue: string = '';
  @Input() models: ModelOption[] = [];
  @Input() disabled: boolean = false;

  @Output() modelValueChange = new EventEmitter<string>();

  @ViewChild('searchInput') searchInput?: ElementRef<HTMLInputElement>;

  isOpen = false;
  searchQuery = '';
  highlightedIndex = 0;
  listboxId = 'listbox-' + Math.random().toString(36).substring(2, 9);

  constructor(private elementRef: ElementRef) {}

  get selectedModel(): ModelOption | undefined {
    return this.models.find(m => m.id === this.modelValue);
  }

  get selectedLabel(): string {
    if (this.selectedModel) {
      return this.selectedModel.label;
    }
    if (this.modelValue) {
      return this.modelValue;
    }
    return 'Seleccionar modelo…';
  }

  get filteredModels(): ModelOption[] {
    const q = this.searchQuery.trim().toLowerCase();
    if (!q) return this.models;
    return this.models.filter(
      m =>
        m.label.toLowerCase().includes(q) ||
        m.id.toLowerCase().includes(q) ||
        m.provider_id.toLowerCase().includes(q) ||
        m.group.toLowerCase().includes(q)
    );
  }

  toggleOpen() {
    if (this.disabled) return;
    this.isOpen = !this.isOpen;
    if (this.isOpen) {
      this.searchQuery = '';
      this.highlightedIndex = 0;
      setTimeout(() => {
        this.searchInput?.nativeElement.focus();
      }, 50);
    }
  }

  close() {
    this.isOpen = false;
  }

  selectModel(model: ModelOption) {
    this.modelValue = model.id;
    this.modelValueChange.emit(model.id);
    this.close();
  }

  onSearchChange() {
    this.highlightedIndex = 0;
  }

  handleKeydown(event: KeyboardEvent) {
    if (!this.isOpen) {
      if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        this.toggleOpen();
      }
      return;
    }

    const count = this.filteredModels.length;

    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        if (count > 0) {
          this.highlightedIndex = (this.highlightedIndex + 1) % count;
        }
        break;
      case 'ArrowUp':
        event.preventDefault();
        if (count > 0) {
          this.highlightedIndex = (this.highlightedIndex - 1 + count) % count;
        }
        break;
      case 'Enter':
        event.preventDefault();
        if (count > 0 && this.filteredModels[this.highlightedIndex]) {
          this.selectModel(this.filteredModels[this.highlightedIndex]);
        }
        break;
      case 'Escape':
        event.preventDefault();
        this.close();
        break;
      case 'Tab':
        this.close();
        break;
    }
  }

  @HostListener('document:click', ['$event'])
  onClickOutside(event: MouseEvent) {
    if (!this.elementRef.nativeElement.contains(event.target)) {
      this.close();
    }
  }
}
