import { CC_STEP_COUNT } from "@/lib/ccProgress";

/** Discrete 1–10 step strip (not a trend chart). */
export function StepLadder({
  current,
  max = CC_STEP_COUNT,
  label,
}: {
  current: number;
  max?: number;
  label: string;
}) {
  const clamped = Math.min(Math.max(1, current), max);
  return (
    <div
      className="flex gap-1"
      role="img"
      aria-label={label}
    >
      {Array.from({ length: max }, (_, i) => {
        const n = i + 1;
        const filled = n <= clamped;
        const isCurrent = n === clamped;
        return (
          <span
            key={n}
            className={
              isCurrent
                ? "h-2 flex-1 rounded-sm bg-teal-700"
                : filled
                  ? "h-2 flex-1 rounded-sm bg-teal-400"
                  : "h-2 flex-1 rounded-sm bg-slate-200"
            }
            title={String(n)}
          />
        );
      })}
    </div>
  );
}
