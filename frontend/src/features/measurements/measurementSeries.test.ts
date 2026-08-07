import { describe, expect, it } from "vitest";

import {
  buildSeries,
  buildTrendSeries,
  formatDelta,
  normalizeMetricKey,
  shiftLocalDate,
} from "@/features/measurements/measurementSeries";

const TODAY = "2026-08-07";

describe("measurementSeries", () => {
  it("normalizes calf_cm alias", () => {
    expect(normalizeMetricKey("calf_cm")).toBe("calves_cm");
    expect(normalizeMetricKey("calves_cm")).toBe("calves_cm");
    expect(normalizeMetricKey("weight_kg")).toBe("weight_kg");
  });

  it("shifts local dates in UTC calendar space", () => {
    expect(shiftLocalDate("2026-08-07", -6)).toBe("2026-08-01");
    expect(shiftLocalDate("2026-03-01", -1)).toBe("2026-02-28");
  });

  it("filters to 7/30/90 day windows inclusive of today", () => {
    const items = [
      {
        local_date: "2026-08-01",
        measured_at: "2026-08-01T08:00:00Z",
        metrics: { schema_version: 1, weight_kg: 80 },
      },
      {
        local_date: "2026-07-15",
        measured_at: "2026-07-15T08:00:00Z",
        metrics: { schema_version: 1, weight_kg: 82 },
      },
      {
        local_date: "2026-05-20",
        measured_at: "2026-05-20T08:00:00Z",
        metrics: { schema_version: 1, weight_kg: 84 },
      },
    ];

    expect(buildSeries(items, "weight_kg", 7, TODAY).points.map((p) => p.local_date)).toEqual([
      "2026-08-01",
    ]);
    expect(buildSeries(items, "weight_kg", 30, TODAY).points.map((p) => p.local_date)).toEqual([
      "2026-07-15",
      "2026-08-01",
    ]);
    expect(buildSeries(items, "weight_kg", 90, TODAY).points.map((p) => p.local_date)).toEqual([
      "2026-05-20",
      "2026-07-15",
      "2026-08-01",
    ]);
  });

  it("reads calf_cm as calves_cm and collapses same-day to newest", () => {
    const items = [
      {
        local_date: "2026-08-05",
        measured_at: "2026-08-05T08:00:00Z",
        metrics: { schema_version: 1, calf_cm: 36 },
      },
      {
        local_date: "2026-08-05",
        measured_at: "2026-08-05T18:00:00Z",
        metrics: { schema_version: 1, calves_cm: 36.5 },
      },
    ];
    const s = buildSeries(items, "calves_cm", 30, TODAY);
    expect(s.points).toEqual([{ local_date: "2026-08-05", value: 36.5 }]);
    expect(s.delta).toBe(0);
  });

  it("returns empty points outside window or missing metric", () => {
    const items = [
      {
        local_date: "2026-01-01",
        measured_at: "2026-01-01T08:00:00Z",
        metrics: { schema_version: 1, weight_kg: 80 },
      },
      {
        local_date: "2026-08-06",
        measured_at: "2026-08-06T08:00:00Z",
        metrics: { schema_version: 1, waist_cm: 80 },
      },
    ];
    expect(buildSeries(items, "weight_kg", 7, TODAY).points).toEqual([]);
    expect(buildSeries(items, "weight_kg", 7, TODAY).delta).toBeNull();
  });

  it("keeps single-point series and computes delta across window", () => {
    const items = [
      {
        local_date: "2026-08-01",
        measured_at: "2026-08-01T08:00:00Z",
        metrics: { schema_version: 1, weight_kg: 80 },
      },
      {
        local_date: "2026-08-07",
        measured_at: "2026-08-07T08:00:00Z",
        metrics: { schema_version: 1, weight_kg: 80.4 },
      },
    ];
    const one = buildSeries(
      [items[0]!],
      "weight_kg",
      30,
      TODAY,
    );
    expect(one.points).toHaveLength(1);
    expect(one.delta).toBe(0);

    const two = buildSeries(items, "weight_kg", 30, TODAY);
    expect(two.delta).toBe(0.4);
    expect(two.first).toBe(80);
    expect(two.last).toBe(80.4);
  });

  it("buildTrendSeries omits metrics without points", () => {
    const items = [
      {
        local_date: "2026-08-07",
        measured_at: "2026-08-07T08:00:00Z",
        metrics: { schema_version: 1, weight_kg: 80, neck_cm: 38 },
      },
    ];
    const series = buildTrendSeries(items, 30, TODAY);
    expect(series.map((s) => s.metric)).toEqual(["weight_kg", "neck_cm"]);
  });

  it("formats delta with sign and unit", () => {
    expect(formatDelta(0.4, "kg")).toMatch(/\+0[,.]4 kg/);
    expect(formatDelta(-1, "cm")).toMatch(/−1 cm/);
    expect(formatDelta(0, "kg")).toBe("0 kg");
    expect(formatDelta(null, "kg")).toBeNull();
  });
});
