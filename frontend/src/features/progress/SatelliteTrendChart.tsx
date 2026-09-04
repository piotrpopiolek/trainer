import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useTranslation } from "react-i18next";

import {
  formatSatelliteDelta,
  type SatelliteMetricSeries,
} from "@/features/progress/satelliteSeries";

export function SatelliteTrendChart({ series }: { series: SatelliteMetricSeries }) {
  const { t } = useTranslation();
  const deltaLabel = formatSatelliteDelta(series.delta, series.unit);
  const single = series.points.length < 2;
  const sideSuffix =
    series.side === "left"
      ? ` (${t("satProgress.sideLeft")})`
      : series.side === "right"
        ? ` (${t("satProgress.sideRight")})`
        : "";

  return (
    <article className="rounded-xl border border-slate-200 bg-white/80 px-3 py-3">
      <header className="mb-2 flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-900">
          {t(series.labelKey)}
          {sideSuffix}
        </h3>
        {deltaLabel ? (
          <p className="text-xs font-medium text-slate-600">
            {t("satProgress.trendsDelta", { delta: deltaLabel })}
          </p>
        ) : null}
      </header>
      {single ? (
        <p className="mb-2 text-xs text-slate-500">{t("satProgress.trendsFewPoints")}</p>
      ) : null}
      <div
        className="h-36 w-full"
        data-testid={`sat-trend-${series.metric}-${series.side}`}
      >
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={series.points}
            margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis
              dataKey="local_date"
              tick={{ fontSize: 10, fill: "#64748b" }}
              tickFormatter={(v: string) => v.slice(5)}
              minTickGap={24}
            />
            <YAxis
              width={36}
              tick={{ fontSize: 10, fill: "#64748b" }}
              domain={["auto", "auto"]}
            />
            <Tooltip
              formatter={(value) => [
                `${value}${series.unit === "reps" ? "" : ` ${series.unit}`}`,
                `${t(series.labelKey)}${sideSuffix}`,
              ]}
              labelFormatter={(label) => String(label)}
              contentStyle={{
                fontSize: 12,
                borderRadius: 8,
                border: "1px solid #e2e8f0",
              }}
            />
            <Line
              type="monotone"
              dataKey="value"
              stroke="#0f766e"
              strokeWidth={2}
              dot={{ r: single ? 5 : 3, fill: "#0f766e" }}
              activeDot={{ r: 5 }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </article>
  );
}
