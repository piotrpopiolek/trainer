/** Build per-metric series for satellite progress charts. */

import { shiftLocalDate, type RangeDays } from "@/features/measurements/measurementSeries";

export type SatelliteMetricKey = "reps" | "duration_sec" | "weight_kg";

export type SatelliteSeriesPoint = {
  local_date: string;
  value: number;
};

export type SatelliteMetricSeries = {
  metric: SatelliteMetricKey;
  unit: "reps" | "s" | "kg";
  labelKey: string;
  side: "combined" | "left" | "right";
  points: SatelliteSeriesPoint[];
  first: number | null;
  last: number | null;
  delta: number | null;
};

export type SatelliteProgressPointLike = {
  local_date: string;
  goal_met?: boolean;
  completed?: boolean | null;
  best_reps?: number | null;
  best_duration_sec?: number | null;
  best_weight_kg?: number | null;
  best_reps_left?: number | null;
  best_reps_right?: number | null;
  best_duration_left?: number | null;
  best_duration_right?: number | null;
  best_weight_left?: number | null;
  best_weight_right?: number | null;
};

const METRIC_META: Record<
  SatelliteMetricKey,
  { unit: "reps" | "s" | "kg"; labelKey: string }
> = {
  reps: { unit: "reps", labelKey: "satProgress.metricReps" },
  duration_sec: { unit: "s", labelKey: "satProgress.metricDuration" },
  weight_kg: { unit: "kg", labelKey: "satProgress.metricWeight" },
};

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

/** Prefer min(L,R) when both sides logged; else overall best. */
export function valueForMetric(
  point: SatelliteProgressPointLike,
  metric: SatelliteMetricKey,
  side: "combined" | "left" | "right" = "combined",
): number | null {
  if (side === "left") {
    if (metric === "reps") return point.best_reps_left ?? null;
    if (metric === "duration_sec") return point.best_duration_left ?? null;
    return point.best_weight_left ?? null;
  }
  if (side === "right") {
    if (metric === "reps") return point.best_reps_right ?? null;
    if (metric === "duration_sec") return point.best_duration_right ?? null;
    return point.best_weight_right ?? null;
  }

  if (metric === "reps") {
    if (point.best_reps_left != null && point.best_reps_right != null) {
      return Math.min(point.best_reps_left, point.best_reps_right);
    }
    return point.best_reps ?? null;
  }
  if (metric === "duration_sec") {
    if (point.best_duration_left != null && point.best_duration_right != null) {
      return Math.min(point.best_duration_left, point.best_duration_right);
    }
    return point.best_duration_sec ?? null;
  }
  if (point.best_weight_left != null && point.best_weight_right != null) {
    return Math.min(point.best_weight_left, point.best_weight_right);
  }
  return point.best_weight_kg ?? null;
}

export function buildSatelliteMetricSeries(
  points: SatelliteProgressPointLike[],
  metric: SatelliteMetricKey,
  rangeDays: RangeDays,
  todayLocalDate: string,
  side: "combined" | "left" | "right" = "combined",
): SatelliteMetricSeries {
  const meta = METRIC_META[metric];
  const start = shiftLocalDate(todayLocalDate, -(rangeDays - 1));
  const filtered = points
    .filter((p) => p.local_date >= start && p.local_date <= todayLocalDate)
    .map((p) => {
      const value = valueForMetric(p, metric, side);
      return value == null ? null : { local_date: p.local_date, value };
    })
    .filter((p): p is SatelliteSeriesPoint => p != null)
    .sort((a, b) => (a.local_date < b.local_date ? -1 : a.local_date > b.local_date ? 1 : 0));

  const first = filtered.length > 0 ? filtered[0]!.value : null;
  const last = filtered.length > 0 ? filtered[filtered.length - 1]!.value : null;
  const delta =
    first != null && last != null ? round1(last - first) : null;

  return {
    metric,
    unit: meta.unit,
    labelKey: meta.labelKey,
    side,
    points: filtered,
    first,
    last,
    delta,
  };
}

export function buildSatelliteTrendSeries(
  points: SatelliteProgressPointLike[],
  activeMetrics: string[],
  rangeDays: RangeDays,
  todayLocalDate: string,
): SatelliteMetricSeries[] {
  const out: SatelliteMetricSeries[] = [];
  const hasSides = activeMetrics.includes("sides");
  for (const m of ["reps", "duration_sec", "weight_kg"] as const) {
    if (!activeMetrics.includes(m)) continue;
    if (hasSides) {
      const left = buildSatelliteMetricSeries(
        points,
        m,
        rangeDays,
        todayLocalDate,
        "left",
      );
      const right = buildSatelliteMetricSeries(
        points,
        m,
        rangeDays,
        todayLocalDate,
        "right",
      );
      if (left.points.length > 0 || right.points.length > 0) {
        if (left.points.length > 0) out.push(left);
        if (right.points.length > 0) out.push(right);
        continue;
      }
    }
    const combined = buildSatelliteMetricSeries(
      points,
      m,
      rangeDays,
      todayLocalDate,
      "combined",
    );
    if (combined.points.length > 0) out.push(combined);
  }
  return out;
}

export function formatSatelliteDelta(
  delta: number | null,
  unit: "reps" | "s" | "kg",
  locale = "pl-PL",
): string | null {
  if (delta == null) return null;
  const abs = Math.abs(delta);
  const formatted = abs.toLocaleString(locale, {
    minimumFractionDigits: Number.isInteger(abs) ? 0 : 1,
    maximumFractionDigits: 1,
  });
  const sign = delta > 0 ? "+" : delta < 0 ? "−" : "";
  const unitLabel = unit === "reps" ? "" : unit === "s" ? " s" : " kg";
  if (delta === 0) return unit === "reps" ? "0" : `0${unitLabel}`;
  return `${sign}${formatted}${unitLabel}`;
}

export function completedDatesInRange(
  points: SatelliteProgressPointLike[],
  rangeDays: RangeDays,
  todayLocalDate: string,
): string[] {
  const start = shiftLocalDate(todayLocalDate, -(rangeDays - 1));
  return points
    .filter(
      (p) =>
        p.local_date >= start &&
        p.local_date <= todayLocalDate &&
        p.completed === true,
    )
    .map((p) => p.local_date)
    .sort();
}
