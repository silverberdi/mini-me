export interface DashboardCostChartSeriesPoint {
  provider: string;
  model: string;
  amount_usd: string;
}

export interface DashboardCostChartPoint {
  x: number;
  y: number;
  label: string;
  displayVal: string;
}

export function toDashboardCostChartPoints(
  input: ReadonlyArray<DashboardCostChartSeriesPoint>,
): DashboardCostChartPoint[] {
  const series = input.slice(-5);
  if (series.length === 0) return [];
  const max = Math.max(...series.map((point) => Number(point.amount_usd)), 0.000001);
  const step = 500 / Math.max(1, series.length - 1);
  return series.map((point, index) => ({
    x: series.length === 1 ? 300 : 70 + index * step,
    y: Math.max(20, Math.round(145 - (Number(point.amount_usd) / max) * 125)),
    label: `${point.provider} · ${point.model}`,
    displayVal: `$${point.amount_usd}`,
  }));
}
