import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui";
import {
  RANGE_OPTIONS,
  type RangeDays,
} from "@/features/measurements/measurementSeries";

export function MeasurementRangeToggle({
  value,
  onChange,
}: {
  value: RangeDays;
  onChange: (days: RangeDays) => void;
}) {
  const { t } = useTranslation();
  return (
    <div
      className="inline-flex rounded-lg border border-slate-300 bg-white p-0.5"
      role="group"
      aria-label={t("measurements.trendsRange")}
    >
      {RANGE_OPTIONS.map((days) => {
        const active = value === days;
        return (
          <Button
            key={days}
            type="button"
            variant={active ? "primary" : "ghost"}
            className={`min-w-12 px-3 py-1.5 text-xs ${active ? "" : "text-slate-600"}`}
            aria-pressed={active}
            onClick={() => onChange(days)}
          >
            {t("measurements.trendsRangeDays", { days })}
          </Button>
        );
      })}
    </div>
  );
}
