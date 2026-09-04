import { describe, expect, it } from "vitest";

import {
  buildSatelliteMetricSeries,
  buildSatelliteTrendSeries,
  completedDatesInRange,
  formatSatelliteDelta,
  valueForMetric,
} from "@/features/progress/satelliteSeries";

const TODAY = "2026-09-04";

const points = [
  {
    local_date: "2026-09-01",
    best_reps: 12,
    best_reps_left: 10,
    best_reps_right: 12,
    best_weight_kg: 12,
    best_weight_left: 12,
    best_weight_right: 12.5,
  },
  {
    local_date: "2026-08-10",
    best_reps: 8,
    best_reps_left: 8,
    best_reps_right: 8,
    best_weight_kg: 10,
  },
  {
    local_date: "2026-07-01",
    best_reps: 5,
    best_weight_kg: 8,
  },
];

describe("satelliteSeries", () => {
  it("uses min(L,R) for combined when both sides present", () => {
    expect(valueForMetric(points[0]!, "reps")).toBe(10);
    expect(valueForMetric(points[0]!, "weight_kg")).toBe(12);
  });

  it("filters 7/30/90 windows", () => {
    expect(
      buildSatelliteMetricSeries(points, "reps", 7, TODAY).points.map((p) => p.local_date),
    ).toEqual(["2026-09-01"]);
    expect(
      buildSatelliteMetricSeries(points, "reps", 30, TODAY).points.map(
        (p) => p.local_date,
      ),
    ).toEqual(["2026-08-10", "2026-09-01"]);
    expect(
      buildSatelliteMetricSeries(points, "reps", 90, TODAY).points.map(
        (p) => p.local_date,
      ),
    ).toEqual(["2026-07-01", "2026-08-10", "2026-09-01"]);
  });

  it("computes delta and single-point series", () => {
    const one = buildSatelliteMetricSeries([points[0]!], "reps", 30, TODAY);
    expect(one.points).toHaveLength(1);
    expect(one.delta).toBe(0);

    const two = buildSatelliteMetricSeries(points, "reps", 30, TODAY);
    expect(two.delta).toBe(2);
  });

  it("splits L/R series when sides active", () => {
    const series = buildSatelliteTrendSeries(
      points,
      ["reps", "weight_kg", "sides"],
      30,
      TODAY,
    );
    expect(series.some((s) => s.side === "left")).toBe(true);
    expect(series.some((s) => s.side === "right")).toBe(true);
  });

  it("lists completed dates for type C", () => {
    const dates = completedDatesInRange(
      [
        { local_date: "2026-09-01", completed: true },
        { local_date: "2026-08-20", completed: false },
        { local_date: "2026-09-03", completed: true },
      ],
      30,
      TODAY,
    );
    expect(dates).toEqual(["2026-09-01", "2026-09-03"]);
  });

  it("formats delta", () => {
    expect(formatSatelliteDelta(2.5, "kg")).toMatch(/\+2[,.]5 kg/);
    expect(formatSatelliteDelta(5, "s")).toMatch(/\+5 s/);
    expect(formatSatelliteDelta(0, "reps")).toBe("0");
  });
});
