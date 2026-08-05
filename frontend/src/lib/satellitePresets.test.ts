/** Golden satellite presets — Hip Thrust + Copenhagen. */

import { describe, expect, it } from "vitest";

import { buildOfflineSatellitePinFromParts } from "@/lib/satelliteOfflinePin";
import {
  SATELLITE_PRESET_IDS,
  buildSatellitePresetCreate,
} from "@/lib/satellitePresets";

describe("satellitePresets", () => {
  it("exposes both plan fixtures", () => {
    expect(SATELLITE_PRESET_IDS).toEqual([
      "sl_hip_thrust_db",
      "copenhagen_plank",
    ]);
  });

  it("builds Hip Thrust goal-only create body", () => {
    const body = buildSatellitePresetCreate("sl_hip_thrust_db");
    expect(body.name).toBe("SL Hip Thrust (DB)");
    expect(body.progression?.mode).toBe("goal_only");
    expect(body.steps).toHaveLength(1);
    expect(body.schedule_kind).toBe("weekdays");
    expect(body.weekdays).toEqual([1, 3, 5]);
    expect(body.active_metrics.metrics.sort()).toEqual(
      ["reps", "sides", "weight_kg"].sort(),
    );
  });

  it("builds Copenhagen multi-step create body", () => {
    const body = buildSatellitePresetCreate("copenhagen_plank");
    expect(body.name).toBe("Copenhagen Plank");
    expect(body.progression?.mode).toBe("steps");
    expect(body.steps).toHaveLength(3);
    expect(body.schedule_category).toBe("post_workout");
    expect(body.steps[2]?.name).toBe("Long lever with bottom leg lifted");
  });

  it("offline pin hashes multi-step Copenhagen document", async () => {
    const body = buildSatellitePresetCreate("copenhagen_plank");
    const pin = await buildOfflineSatellitePinFromParts({
      exercise_type: body.exercise_type,
      activeMetrics: body.active_metrics,
      progression: body.progression!,
      steps: body.steps.map((s) => ({
        step_id: s.step_id,
        step_number: s.step_number,
        name: s.name ?? null,
        rules: s.rules,
      })),
      configVersionId: body.config_version_id,
    });
    expect(pin.configHash).toMatch(/^[a-f0-9]{64}$/);
    expect(pin.steps).toHaveLength(3);
  });
});
