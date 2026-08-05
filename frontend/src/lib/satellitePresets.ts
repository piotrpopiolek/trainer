/** Golden satellite create presets (Hip Thrust + Copenhagen) — mirror backend domain. */

import {
  activeMetricsSchema,
  satelliteProgressionPolicySchema,
  satelliteRulesSchema,
  type SatelliteProgressionPolicy,
  type SatelliteRules,
} from "@/lib/satelliteContracts";
import { newClientMutationId } from "@/lib/uuid";

export type SatellitePresetId = "sl_hip_thrust_db" | "copenhagen_plank";

export const SATELLITE_PRESET_IDS: SatellitePresetId[] = [
  "sl_hip_thrust_db",
  "copenhagen_plank",
];

export type SatelliteCreateRequest = {
  schema_version: 1;
  name: string;
  exercise_type: "B" | "C";
  active_metrics: { schema_version: 1; metrics: string[] };
  equipment?: string[];
  tags?: string[];
  schedule_kind: "daily" | "weekdays" | "category";
  weekdays?: number[] | null;
  schedule_category?: "anytime" | "post_workout" | "rest_day" | null;
  progression?: SatelliteProgressionPolicy;
  steps: Array<{
    step_number: number;
    step_id?: string;
    name?: string | null;
    rules: SatelliteRules;
  }>;
  config_version_id?: string;
  client_mutation_id?: string;
};

const META: Record<
  SatellitePresetId,
  { defaultName: string; summaryKey: string }
> = {
  sl_hip_thrust_db: {
    defaultName: "SL Hip Thrust (DB)",
    summaryKey: "satellites.presetHipThrustHint",
  },
  copenhagen_plank: {
    defaultName: "Copenhagen Plank",
    summaryKey: "satellites.presetCopenhagenHint",
  },
};

export function satellitePresetMeta(id: SatellitePresetId) {
  return META[id];
}

function durationRules(minDurationSec: number): SatelliteRules {
  return satelliteRulesSchema.parse({
    schema_version: 1,
    goal: {
      type: "duration",
      sets: 3,
      min_duration_sec: minDurationSec,
      require_both_sides: true,
    },
  });
}

export function buildSatellitePresetCreate(
  presetId: SatellitePresetId,
  opts?: {
    name?: string;
    clientMutationId?: string;
    stepIds?: string[];
    configVersionId?: string;
  },
): SatelliteCreateRequest {
  const mutationId = opts?.clientMutationId ?? newClientMutationId();
  const stepId = (i: number) => opts?.stepIds?.[i] ?? newClientMutationId();

  if (presetId === "sl_hip_thrust_db") {
    const metrics = activeMetricsSchema.parse({
      schema_version: 1,
      metrics: ["reps", "weight_kg", "sides"],
    });
    const body: SatelliteCreateRequest = {
      schema_version: 1,
      name: opts?.name ?? META.sl_hip_thrust_db.defaultName,
      exercise_type: "B",
      active_metrics: {
        schema_version: 1,
        metrics: [...metrics.metrics].sort(),
      },
      equipment: ["dumbbell", "bench"],
      schedule_kind: "weekdays",
      weekdays: [1, 3, 5],
      progression: satelliteProgressionPolicySchema.parse({ mode: "goal_only" }),
      steps: [
        {
          step_number: 1,
          step_id: stepId(0),
          name: "Working sets",
          rules: satelliteRulesSchema.parse({
            schema_version: 1,
            goal: {
              type: "reps",
              sets: 3,
              min_reps: 10,
              require_both_sides: true,
              min_weight_kg: null,
            },
          }),
        },
      ],
      client_mutation_id: mutationId,
    };
    if (opts?.configVersionId) body.config_version_id = opts.configVersionId;
    return body;
  }

  const metrics = activeMetricsSchema.parse({
    schema_version: 1,
    metrics: ["duration_sec", "sides"],
  });
  const body: SatelliteCreateRequest = {
    schema_version: 1,
    name: opts?.name ?? META.copenhagen_plank.defaultName,
    exercise_type: "B",
    active_metrics: {
      schema_version: 1,
      metrics: [...metrics.metrics].sort(),
    },
    equipment: ["bench"],
    schedule_kind: "category",
    schedule_category: "post_workout",
    progression: satelliteProgressionPolicySchema.parse({
      mode: "steps",
      regression: {
        mode: "suggest_after_failed_days",
        threshold: 2,
      },
    }),
    steps: [
      {
        step_number: 1,
        step_id: stepId(0),
        name: "Short lever hold",
        rules: durationRules(20),
      },
      {
        step_number: 2,
        step_id: stepId(1),
        name: "Long lever hold",
        rules: durationRules(20),
      },
      {
        step_number: 3,
        step_id: stepId(2),
        name: "Long lever with bottom leg lifted",
        rules: durationRules(15),
      },
    ],
    client_mutation_id: mutationId,
  };
  if (opts?.configVersionId) body.config_version_id = opts.configVersionId;
  return body;
}
