/** Shared display helpers for CC progress / step rules. */

type Threshold = {
  sets?: number;
  min_reps?: number | null;
  min_duration_sec?: number | null;
  require_both_sides?: boolean;
};

export function formatThreshold(raw: unknown): string {
  if (!raw || typeof raw !== "object") return "";
  const a = raw as Threshold;
  const both = a.require_both_sides ? " L/P" : "";
  if (typeof a.min_duration_sec === "number") {
    const sets = typeof a.sets === "number" && a.sets > 1 ? `${a.sets}×` : "";
    return `${sets}${a.min_duration_sec}s${both}`;
  }
  if (typeof a.sets === "number" && typeof a.min_reps === "number") {
    return `${a.sets}×${a.min_reps}${both}`;
  }
  return "";
}

export function standardsFromRules(rules: Record<string, unknown> | undefined): {
  beginner: string;
  intermediate: string;
  progression: string;
} {
  const standards =
    rules && typeof rules.standards === "object" && rules.standards
      ? (rules.standards as Record<string, unknown>)
      : {};
  return {
    beginner: formatThreshold(standards.beginner),
    intermediate: formatThreshold(standards.intermediate),
    progression: formatThreshold(
      standards.progression ?? rules?.advance ?? rules?.progression,
    ),
  };
}

export function formatLastSessionAt(
  iso: string | null | undefined,
  emptyLabel: string,
  locale = "pl-PL",
): string {
  if (!iso) return emptyLabel;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return emptyLabel;
  return d.toLocaleDateString(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
