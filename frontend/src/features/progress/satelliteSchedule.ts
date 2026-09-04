/** Format satellite schedule for list cards (i18n keys, no hardcoded PL in callers). */

export function scheduleLabelKey(item: {
  schedule_kind?: string | null;
  weekdays?: number[] | null;
  schedule_category?: string | null;
}): { key: string; weekdays?: number[] } {
  if (item.schedule_kind === "daily") {
    return { key: "satProgress.scheduleDaily" };
  }
  if (item.schedule_kind === "category") {
    if (item.schedule_category === "post_workout") {
      return { key: "satProgress.schedulePostWorkout" };
    }
    if (item.schedule_category === "rest_day") {
      return { key: "satProgress.scheduleRestDay" };
    }
    return { key: "satProgress.scheduleAnytime" };
  }
  if (item.schedule_kind === "weekdays" && item.weekdays?.length) {
    return { key: "satProgress.scheduleWeekdays", weekdays: item.weekdays };
  }
  return { key: "satProgress.scheduleUnknown" };
}

const WEEKDAY_KEYS = [
  "",
  "satProgress.weekdayMon",
  "satProgress.weekdayTue",
  "satProgress.weekdayWed",
  "satProgress.weekdayThu",
  "satProgress.weekdayFri",
  "satProgress.weekdaySat",
  "satProgress.weekdaySun",
] as const;

export function weekdayLabelKeys(weekdays: number[]): string[] {
  return weekdays
    .filter((d) => d >= 1 && d <= 7)
    .map((d) => WEEKDAY_KEYS[d]!);
}

export function activeMetricNames(raw: unknown): string[] {
  if (!raw || typeof raw !== "object") return [];
  const metrics = (raw as { metrics?: unknown }).metrics;
  if (!Array.isArray(metrics)) return [];
  return metrics.filter((m): m is string => typeof m === "string");
}
