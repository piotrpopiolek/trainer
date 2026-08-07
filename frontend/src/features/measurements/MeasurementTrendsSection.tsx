import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { MeasurementRangeToggle } from "@/features/measurements/MeasurementRangeToggle";
import { MeasurementTrendChart } from "@/features/measurements/MeasurementTrendChart";
import {
  buildTrendSeries,
  type RangeDays,
} from "@/features/measurements/measurementSeries";
import type { Measurement } from "@/lib/schemas";

export function MeasurementTrendsSection({
  items,
  todayLocalDate,
}: {
  items: Measurement[];
  todayLocalDate: string;
}) {
  const { t } = useTranslation();
  const [rangeDays, setRangeDays] = useState<RangeDays>(30);

  const series = useMemo(
    () => buildTrendSeries(items, rangeDays, todayLocalDate),
    [items, rangeDays, todayLocalDate],
  );

  return (
    <section className="flex flex-col gap-3" aria-labelledby="measurements-trends-heading">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2
          id="measurements-trends-heading"
          className="font-display text-lg font-semibold text-slate-900"
        >
          {t("measurements.trendsTitle")}
        </h2>
        <MeasurementRangeToggle value={rangeDays} onChange={setRangeDays} />
      </div>
      {series.length === 0 ? (
        <p className="text-sm text-slate-500">{t("measurements.trendsEmpty")}</p>
      ) : (
        <div className="flex flex-col gap-3">
          {series.map((s) => (
            <MeasurementTrendChart key={s.metric} series={s} />
          ))}
        </div>
      )}
    </section>
  );
}
