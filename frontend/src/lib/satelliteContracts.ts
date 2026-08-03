/** Satellite write contracts (Stage 1) — mirror backend SatelliteRulesV1 / LogResult. */

import { z } from "zod";

const schemaVersion = z.number().int().gte(1);

const weightKg = z
  .string()
  .regex(/^(?:0|[1-9]\d*)\.\d{3}$/, "weight_kg_must_be_decimal_string");

const sideName = z.enum(["left", "right", "bilateral"]);

export const activeMetricsSchema = z.object({
  schema_version: schemaVersion,
  metrics: z.array(z.enum(["reps", "duration_sec", "weight_kg", "sides"])),
});

const goalRepsSchema = z
  .object({
    type: z.literal("reps"),
    sets: z.number().int().gte(1),
    min_reps: z.number().int().gte(1),
    min_weight_kg: weightKg.nullable().optional(),
    require_both_sides: z.boolean().optional().default(false),
  })
  .strict();

const goalDurationSchema = z
  .object({
    type: z.literal("duration"),
    sets: z.number().int().gte(1),
    min_duration_sec: z.number().int().gte(1),
    min_weight_kg: weightKg.nullable().optional(),
    require_both_sides: z.boolean().optional().default(false),
  })
  .strict();

const goalCompletedSchema = z
  .object({
    type: z.literal("completed"),
  })
  .strict();

export const satelliteGoalSchema = z.discriminatedUnion("type", [
  goalRepsSchema,
  goalDurationSchema,
  goalCompletedSchema,
]);

export const satelliteRulesSchema = z
  .object({
    schema_version: schemaVersion,
    goal: satelliteGoalSchema,
  })
  .strict()
  .superRefine((val, ctx) => {
    const banned = ["advance", "regress", "standards", "fail_sessions"] as const;
    for (const key of banned) {
      if (key in (val as Record<string, unknown>)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: `satellite_rules_forbid_${key}`,
        });
      }
    }
  });

export const satelliteSetSchema = z
  .object({
    reps: z.number().int().gte(0).nullable().optional(),
    duration_sec: z.number().int().gte(0).nullable().optional(),
    weight_kg: weightKg.nullable().optional(),
    sides: sideName.nullable().optional(),
    notes: z.string().max(1000).nullable().optional(),
  })
  .strict()
  .superRefine((val, ctx) => {
    if (
      val.reps == null &&
      val.duration_sec == null &&
      val.weight_kg == null &&
      val.sides == null &&
      val.notes == null
    ) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: "empty_set" });
    }
  });

export const satelliteLogResultSchema = z
  .object({
    schema_version: schemaVersion,
    completed: z.boolean().nullable().optional(),
    sets: z.array(satelliteSetSchema).default([]),
  })
  .strict();

export const satelliteRegressionPolicySchema = z
  .object({
    mode: z.literal("suggest_after_failed_days"),
    threshold: z.number().int().gte(1),
  })
  .strict();

export const satelliteProgressionPolicySchema = z.discriminatedUnion("mode", [
  z.object({ mode: z.literal("goal_only") }).strict(),
  z
    .object({
      mode: z.literal("steps"),
      regression: satelliteRegressionPolicySchema,
    })
    .strict(),
]);

export const satelliteConfigStepSchema = z
  .object({
    step_id: z.string().uuid(),
    sort_order: z.number().int().gte(1),
    rules: satelliteRulesSchema,
  })
  .strict();

export const satelliteConfigDocumentSchema = z
  .object({
    schema_version: schemaVersion,
    exercise_type: z.enum(["B", "C"]),
    active_metrics: activeMetricsSchema,
    progression: satelliteProgressionPolicySchema,
    steps: z.array(satelliteConfigStepSchema).min(1).max(5),
  })
  .strict()
  .superRefine((doc, ctx) => {
    if (doc.progression.mode === "goal_only" && doc.steps.length !== 1) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "goal_only_requires_one_step",
      });
    }
    if (
      doc.progression.mode === "steps" &&
      (doc.steps.length < 2 || doc.steps.length > 5)
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "steps_mode_requires_2_to_5",
      });
    }
  });

export type SatelliteLogResult = z.infer<typeof satelliteLogResultSchema>;
export type SatelliteRules = z.infer<typeof satelliteRulesSchema>;
export type SatelliteProgressionPolicy = z.infer<
  typeof satelliteProgressionPolicySchema
>;
export type SatelliteConfigDocument = z.infer<typeof satelliteConfigDocumentSchema>;

/** Canonical weight string via integer grams (avoids float drift). */
export function weightKgFromGrams(grams: number): string {
  if (!Number.isInteger(grams) || grams <= 0) {
    throw new Error("invalid_weight_grams");
  }
  const whole = Math.floor(grams / 1000);
  const frac = grams % 1000;
  return `${whole}.${String(frac).padStart(3, "0")}`;
}

export function parseWeightInputToKgString(raw: string): string {
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) {
    throw new Error("invalid_weight_kg");
  }
  const grams = Math.round(n * 1000);
  return weightKgFromGrams(grams);
}
