export interface HumanGateDisplayOption {
  label: string;
  original: string;
  description: string;
  value: string;
  source?: string;
}

export interface HumanGatePresentation {
  summary: string;
  pendingItems: string[];
  options: HumanGateDisplayOption[];
}

function cleanItems(value: unknown): string[] {
  if (typeof value === 'string') return value.split(';').map(item => item.trim()).filter(Boolean);
  if (!Array.isArray(value)) return [];
  return value.flatMap(item => {
    if (typeof item === 'string') return cleanItems(item);
    if (!item || typeof item !== 'object') return [];
    const record = item as Record<string, unknown>;
    return cleanItems(record['description'] || record['reason'] || record['text'] || record['title']);
  });
}

export function normalizeHumanGatePayload(payload: any): HumanGatePresentation {
  const source = payload && typeof payload === 'object' ? payload : {};
  const pendingItems = cleanItems(source['pending_items']).length
    ? cleanItems(source['pending_items'])
    : cleanItems(source['blockers'] || source['pending_tasks'] || source['description']);
  const rawOptions = Array.isArray(source['options']) ? source['options'] : [];
  const translated = Array.isArray(source['options_es']) ? source['options_es'] : [];
  const explanations = Array.isArray(source['option_explanations']) ? source['option_explanations'] : [];
  const options = rawOptions.map((option: any, index: number) => {
    const original = typeof option === 'string'
      ? option
      : String(option?.label || option?.id || option?.response_text || '');
    const explanation = explanations[index];
    return {
      label: String(translated[index] || option?.label_es || original || `Opción ${index + 1}`).trim(),
      original,
      description: typeof explanation === 'string'
        ? explanation
        : String(explanation?.consequence || option?.description || '').trim(),
      value: typeof option === 'object' ? String(option?.response_text || option?.label || option?.id || '') : original,
      source: typeof option === 'object' ? option?.source : undefined,
    };
  });
  return {
    summary: String(source['summary_es'] || source['explanation_es'] || source['description'] || '').trim(),
    pendingItems,
    options,
  };
}
