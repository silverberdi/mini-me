export const historyView = "history";
export function filterHistory(items = [], query = "") { const term = query.trim().toLowerCase(); return term ? items.filter((item) => JSON.stringify(item).toLowerCase().includes(term)) : items; }
