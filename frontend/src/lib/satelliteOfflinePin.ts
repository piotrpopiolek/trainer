/** Offline satellite config pin (Stage 2 Slice D) — client-stable IDs + JCS hash. */

import { sha256JcsHex } from "@/lib/canonicalJson";
import {
  activeMetricsSchema,
  satelliteRulesSchema,
  type SatelliteProgressionPolicy,
  type SatelliteRules,
} from "@/lib/satelliteContracts";
import { newClientMutationId } from "@/lib/uuid";

export type OfflineSatellitePin = {
  configVersionId: string;
  configHash: string;
  document: Record<string, unknown>;
  steps: Array<{
    step_id: string;
    step_number: number;
    name: string | null;
    rules: SatelliteRules;
  }>;
  activeMetrics: { schema_version: 1; metrics: string[] };
};

function buildRulesForPin(input: {
  exercise_type: "B" | "C";
  goalSets?: number;
  goalReps?: number;
  requireBothSides?: boolean;
}): SatelliteRules {
  if (input.exercise_type === "C") {
    return satelliteRulesSchema.parse({
      schema_version: 1,
      goal: { type: "completed" },
    });
  }
  return satelliteRulesSchema.parse({
    schema_version: 1,
    goal: {
      type: "reps",
      sets: input.goalSets ?? 3,
      min_reps: input.goalReps ?? 10,
      min_weight_kg: null,
      require_both_sides: input.requireBothSides ?? false,
    },
  });
}

function buildActiveMetrics(input: {
  exercise_type: "B" | "C";
  trackWeight?: boolean;
  requireBothSides?: boolean;
}): { schema_version: 1; metrics: string[] } {
  if (input.exercise_type === "C") {
    return activeMetricsSchema.parse({
      schema_version: 1,
      metrics: [],
    }) as { schema_version: 1; metrics: string[] };
  }
  const metrics: string[] = ["reps"];
  if (input.trackWeight) metrics.push("weight_kg");
  if (input.requireBothSides) metrics.push("sides");
  return activeMetricsSchema.parse({
    schema_version: 1,
    metrics: [...metrics].sort(),
  }) as { schema_version: 1; metrics: string[] };
}

/** Build immutable config document + hash matching backend SatelliteConfigDocumentV1. */
export async function buildOfflineSatellitePin(input: {
  exercise_type: "B" | "C";
  stepName: string;
  goalSets?: number;
  goalReps?: number;
  requireBothSides?: boolean;
  trackWeight?: boolean;
  configVersionId?: string;
  stepId?: string;
}): Promise<OfflineSatellitePin> {
  const configVersionId = input.configVersionId ?? newClientMutationId();
  const stepId = input.stepId ?? newClientMutationId();
  const rules = buildRulesForPin(input);
  const activeMetrics = buildActiveMetrics(input);
  return buildOfflineSatellitePinFromParts({
    exercise_type: input.exercise_type,
    activeMetrics,
    progression: { mode: "goal_only" },
    steps: [
      {
        step_id: stepId,
        step_number: 1,
        name: input.stepName,
        rules,
      },
    ],
    configVersionId,
  });
}

/** Multi-step / preset create — same document shape as backend SatelliteConfigDocumentV1. */
export async function buildOfflineSatellitePinFromParts(input: {
  exercise_type: "B" | "C";
  activeMetrics: { schema_version: 1; metrics: string[] };
  progression: SatelliteProgressionPolicy;
  steps: Array<{
    step_id?: string;
    step_number: number;
    name: string | null;
    rules: SatelliteRules;
  }>;
  configVersionId?: string;
}): Promise<OfflineSatellitePin> {
  const configVersionId = input.configVersionId ?? newClientMutationId();
  const activeMetrics = activeMetricsSchema.parse({
    schema_version: 1,
    metrics: [...input.activeMetrics.metrics].sort(),
  }) as { schema_version: 1; metrics: string[] };
  const steps = input.steps.map((s) => {
    const step_id = s.step_id ?? newClientMutationId();
    const rules = satelliteRulesSchema.parse(s.rules);
    return {
      step_id,
      step_number: s.step_number,
      name: s.name,
      rules,
    };
  });
  const document: Record<string, unknown> = {
    schema_version: 1,
    exercise_type: input.exercise_type,
    active_metrics: activeMetrics,
    progression: input.progression,
    steps: steps.map((s) => ({
      step_id: s.step_id,
      sort_order: s.step_number,
      rules: s.rules,
    })),
  };
  const configHash = await sha256JcsHex(document);
  return {
    configVersionId,
    configHash,
    document,
    activeMetrics,
    steps,
  };
}
