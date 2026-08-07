/** Build per-metric time series for body measurement trend charts (FR-131 / FR-132). */

export type RangeDays = 7 | 30 | 90;

export type MetricKey =
  | "weight_kg"
  | "waist_cm"
  | "biceps_cm"
  | "chest_cm"
  | "thigh_cm"
  | "neck_cm"
  | "abdomen_cm"
  | "hips_cm"
  | "calves_cm";

export type MetricUnit = "kg" | "cm";

export type MetricDef = {
  key: MetricKey;
  unit: MetricUnit;
  labelKey: string;
};

/** Stable catalog order: weight first, then F1 circumferences. */
export const METRIC_CATALOG: readonly MetricDef[] = [
  { key: "weight_kg", unit: "kg", labelKey: "measurements.weight" },
  { key: "waist_cm", unit: "cm", labelKey: "measurements.waist" },
  { key: "biceps_cm", unit: "cm", labelKey: "measurements.biceps" },
  { key: "chest_cm", unit: "cm", labelKey: "measurements.chest" },
  { key: "thigh_cm", unit: "cm", labelKey: "measurements.thigh" },
  { key: "neck_cm", unit: "cm", labelKey: "measurements.neck" },
  { key: "abdomen_cm", unit: "cm", labelKey: "measurements.abdomen" },
  { key: "hips_cm", unit: "cm", labelKey: "measurements.hips" },
  { key: "calves_cm", unit: "cm", labelKey: "measurements.calf" },
] as const;

export const RANGE_OPTIONS: readonly RangeDays[] = [7, 30, 90];

export type SeriesPoint = {
  local_date: string;
  value: number;
};

export type MetricSeries = {
  metric: MetricKey;
  unit: MetricUnit;
  labelKey: string;
  points: SeriesPoint[];
  first: number | null;
  last: number | null;
  delta: number | null;
};

type MeasurementLike = {
  local_date: string;
  measured_at?: string;
  metrics: Record<string, unknown>;
};

/** Canonicalize API alias `calf_cm` → `calves_cm`. */
export function normalizeMetricKey(key: string): string {
  if (key === "calf_cm") return "calves_cm";
  return key;
}

export function shiftLocalDate(isoDate: string, days: number): string {
  const parts = isoDate.split("-").map(Number);
  const y = parts[0] ?? 0;
  const m = parts[1] ?? 1;
  const d = parts[2] ?? 1;
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() + days);
  return dt.toISOString().slice(0, 10);
}

function readMetricValue(
  metrics: Record<string, unknown>,
  metric: MetricKey,
): number | null {
  let raw: unknown = metrics[metric];
  if (metric === "calves_cm" && (raw == null || raw === "")) {
    raw = metrics.calf_cm;
  }
  if (typeof raw !== "number" || !Number.isFinite(raw)) return null;
  return raw;
}

export function buildSeries(
  items: MeasurementLike[],
  metric: MetricKey,
  rangeDays: RangeDays,
  todayLocalDate: string,
): MetricSeries {
  const def = METRIC_CATALOG.find((m) => m.key === metric)!;
  const start = shiftLocalDate(todayLocalDate, -(rangeDays - 1));

  const inWindow = items.filter(
    (it) => it.local_date >= start && it.local_date <= todayLocalDate,
  );

  // Newest first within a day wins when collapsing to one point per date.
  const byDate = new Map<string, { value: number; measured_at: string }>();
  const sortedNewest = [...inWindow].sort((a, b) => {
    if (a.local_date !== b.local_date) return a.local_date < b.local_date ? 1 : -1;
    const am = a.measured_at ?? "";
    const bm = b.measured_at ?? "";
    return am < bm ? 1 : am > bm ? -1 : 0;
  });

  for (const it of sortedNewest) {
    if (byDate.has(it.local_date)) continue;
    const value = readMetricValue(it.metrics, metric);
    if (value == null) continue;
    byDate.set(it.local_date, {
      value,
      measured_at: it.measured_at ?? "",
    });
  }

  const points: SeriesPoint[] = [...byDate.entries()]
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([local_date, { value }]) => ({ local_date, value }));

  const first = points.length > 0 ? points[0]!.value : null;
  const last = points.length > 0 ? points[points.length - 1]!.value : null;
  const delta =
    first != null && last != null ? Math.round((last - first) * 10) / 10 : null;

  return {
    metric,
    unit: def.unit,
    labelKey: def.labelKey,
    points,
    first,
    last,
    delta,
  };
}

/** Series for every catalog metric that has ≥1 point in the window. */
export function buildTrendSeries(
  items: MeasurementLike[],
  rangeDays: RangeDays,
  todayLocalDate: string,
): MetricSeries[] {
  return METRIC_CATALOG.map((m) =>
    buildSeries(items, m.key, rangeDays, todayLocalDate),
  ).filter((s) => s.points.length > 0);
}

export function formatDelta(
  delta: number | null,
  unit: MetricUnit,
  locale = "pl-PL",
): string | null {
  if (delta == null) return null;
  const abs = Math.abs(delta);
  const formatted = abs.toLocaleString(locale, {
    minimumFractionDigits: Number.isInteger(abs) ? 0 : 1,
    maximumFractionDigits: 1,
  });
  const sign = delta > 0 ? "+" : delta < 0 ? "−" : "";
  const unitLabel = unit === "kg" ? "kg" : "cm";
  if (delta === 0) return `0 ${unitLabel}`;
  return `${sign}${formatted} ${unitLabel}`;
}
