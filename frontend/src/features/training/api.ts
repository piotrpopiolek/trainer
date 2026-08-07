import { apiJson } from "@/lib/api";
import {
  catalogCcResponseSchema,
  measurementSchema,
  progressItemSchema,
  progressionEventSchema,
  satelliteSchema,
  sessionSchema,
  todaySchema,
  type Measurement,
  type ProgressItem,
  type ProgressionEvent,
  type Satellite,
  type Session,
  type Today,
} from "@/lib/schemas";
import type { CatalogCcExercise } from "@/lib/schemas";
import { newClientMutationId } from "@/lib/uuid";
import { useAuthStore } from "@/stores/authStore";
import { z } from "zod";

export async function fetchToday(params?: {
  localDate?: string;
  ccDayOverride?: number;
}): Promise<Today> {
  const q = new URLSearchParams();
  if (params?.localDate) q.set("local_date", params.localDate);
  if (params?.ccDayOverride != null) q.set("cc_day_override", String(params.ccDayOverride));
  const qs = q.toString();
  const raw = await apiJson<unknown>(`/api/today${qs ? `?${qs}` : ""}`);
  return todaySchema.parse(raw);
}

export async function createSession(input: {
  performedAt: string;
  localDate: string;
  clientTimezone: string;
  notes?: string;
  logs: Array<{
    exercise_id: string;
    exercise_kind: "cc" | "satellite";
    section?: "main" | "accessories";
    skipped?: boolean;
    sets?: {
      schema_version: number;
      completed?: boolean | null;
      sets: Array<{
        reps?: number;
        duration_sec?: number;
        weight_kg?: string;
        sides?: "left" | "right" | "bilateral";
      }>;
    };
    notes?: string;
    sort_order?: number;
    satellite_config_version_id?: string;
    satellite_config_hash?: string;
  }>;
}): Promise<Session> {
  const raw = await apiJson<unknown>("/api/sessions", {
    method: "POST",
    body: JSON.stringify({
      schema_version: 1,
      performed_at: input.performedAt,
      local_date: input.localDate,
      client_mutation_id: newClientMutationId(),
      client_timezone: input.clientTimezone,
      notes: input.notes,
      logs: input.logs,
    }),
  });
  return sessionSchema.parse(raw);
}

export async function softDeleteSession(sessionId: string): Promise<Session> {
  const raw = await apiJson<unknown>(`/api/sessions/${sessionId}`, {
    method: "DELETE",
  });
  return sessionSchema.parse(raw);
}

export async function listSatellites(): Promise<Satellite[]> {
  const raw = await apiJson<{ items: unknown[] }>("/api/satellites");
  return z.array(satelliteSchema).parse(raw.items);
}

import type { SatelliteCreateRequest } from "@/lib/satellitePresets";

export async function createSatelliteFromBody(
  body: SatelliteCreateRequest,
): Promise<Satellite> {
  const raw = await apiJson<unknown>("/api/satellites", {
    method: "POST",
    body: JSON.stringify({
      ...body,
      client_mutation_id: body.client_mutation_id ?? newClientMutationId(),
    }),
  });
  return satelliteSchema.parse(raw);
}

export async function createSatellite(input: {
  name: string;
  exercise_type: "B" | "C";
  schedule_kind: "daily" | "weekdays" | "category";
  weekdays?: number[];
  schedule_category?: "anytime" | "post_workout" | "rest_day";
  goalReps?: number;
  goalSets?: number;
  requireBothSides?: boolean;
  trackWeight?: boolean;
  stepName: string;
}): Promise<Satellite> {
  const isTypeC = input.exercise_type === "C";
  const metrics: string[] = [];
  if (!isTypeC) {
    metrics.push("reps");
    if (input.trackWeight) metrics.push("weight_kg");
    if (input.requireBothSides) metrics.push("sides");
  }
  const goal = isTypeC
    ? { type: "completed" as const }
    : {
        type: "reps" as const,
        sets: input.goalSets ?? 3,
        min_reps: input.goalReps ?? 10,
        require_both_sides: input.requireBothSides ?? false,
        min_weight_kg: null,
      };
  return createSatelliteFromBody({
    schema_version: 1,
    name: input.name,
    exercise_type: input.exercise_type,
    active_metrics: { schema_version: 1, metrics },
    schedule_kind: input.schedule_kind,
    weekdays: input.weekdays,
    schedule_category: input.schedule_category,
    steps: [
      {
        step_number: 1,
        name: input.stepName,
        rules: {
          schema_version: 1,
          goal,
        },
      },
    ],
  });
}

function satelliteStepsForWrite(
  steps: Array<Record<string, unknown>>,
): Array<Record<string, unknown>> {
  return steps.map((s) => {
    const stepNumber = Number(s.step_number ?? s.sort_order);
    const out: Record<string, unknown> = {
      step_number: Number.isFinite(stepNumber) && stepNumber >= 1 ? stepNumber : 1,
      rules: s.rules,
    };
    if (typeof s.step_id === "string") out.step_id = s.step_id;
    if (s.name !== undefined) out.name = s.name;
    if (s.description !== undefined) out.description = s.description;
    return out;
  });
}

function progressionForWrite(
  steps: Array<Record<string, unknown>>,
  progression?: { mode: "goal_only" } | { mode: "steps"; regression: unknown },
): { mode: "goal_only" } | { mode: "steps"; regression: unknown } {
  if (progression?.mode === "goal_only") return { mode: "goal_only" };
  if (progression?.mode === "steps") {
    return {
      mode: "steps",
      regression: progression.regression ?? {
        mode: "suggest_after_failed_days",
        threshold: 2,
      },
    };
  }
  if (steps.length <= 1) return { mode: "goal_only" };
  return {
    mode: "steps",
    regression: { mode: "suggest_after_failed_days", threshold: 2 },
  };
}

export async function updateSatellite(input: {
  id: string;
  revision: number;
  name: string;
  exercise_type: "B" | "C";
  schedule_kind: "daily" | "weekdays" | "category";
  weekdays?: number[] | null;
  schedule_category?: "anytime" | "post_workout" | "rest_day" | null;
  active_metrics: unknown;
  equipment?: string[];
  tags?: string[];
  steps: Array<Record<string, unknown>>;
  progression?: { mode: "goal_only" } | { mode: "steps"; regression: unknown };
  expected_current_config_version_id?: string | null;
}): Promise<Satellite> {
  const csrf = useAuthStore.getState().me?.csrf_token;
  const steps = satelliteStepsForWrite(input.steps);
  const raw = await apiJson<unknown>(`/api/satellites/${input.id}`, {
    method: "PATCH",
    csrfToken: csrf,
    body: JSON.stringify({
      schema_version: 1,
      revision: input.revision,
      name: input.name,
      exercise_type: input.exercise_type,
      active_metrics: input.active_metrics,
      equipment: input.equipment ?? [],
      tags: input.tags ?? [],
      schedule_kind: input.schedule_kind,
      weekdays: input.weekdays ?? null,
      schedule_category: input.schedule_category ?? null,
      progression: progressionForWrite(steps, input.progression),
      steps,
      client_mutation_id: newClientMutationId(),
      config_version_id: newClientMutationId(),
      expected_current_config_version_id:
        input.expected_current_config_version_id ?? null,
    }),
  });
  return satelliteSchema.parse(raw);
}

export async function cloneSatellite(
  exerciseId: string,
  input?: { name?: string },
): Promise<Satellite> {
  const raw = await apiJson<unknown>(`/api/satellites/${exerciseId}/clone`, {
    method: "POST",
    body: JSON.stringify({
      schema_version: 1,
      client_mutation_id: newClientMutationId(),
      name: input?.name,
    }),
  });
  return satelliteSchema.parse(raw);
}

export async function listMeasurements(): Promise<Measurement[]> {
  const raw = await apiJson<{ items: unknown[] }>("/api/measurements");
  return z.array(measurementSchema).parse(raw.items);
}

export async function createMeasurement(input: {
  measuredAt: string;
  localDate: string;
  weightKg?: number;
  waistCm?: number;
  bicepsCm?: number;
  chestCm?: number;
  thighCm?: number;
  neckCm?: number;
  abdomenCm?: number;
  hipsCm?: number;
  calvesCm?: number;
  notes?: string;
}): Promise<Measurement> {
  const metrics: Record<string, number | undefined> & { schema_version: number } = {
    schema_version: 1,
    weight_kg: input.weightKg,
    waist_cm: input.waistCm,
    biceps_cm: input.bicepsCm,
    chest_cm: input.chestCm,
    thigh_cm: input.thighCm,
    neck_cm: input.neckCm,
    abdomen_cm: input.abdomenCm,
    hips_cm: input.hipsCm,
    calves_cm: input.calvesCm,
  };
  const raw = await apiJson<unknown>("/api/measurements", {
    method: "POST",
    body: JSON.stringify({
      schema_version: 1,
      measured_at: input.measuredAt,
      local_date: input.localDate,
      metrics,
      notes: input.notes,
      client_mutation_id: newClientMutationId(),
    }),
  });
  return measurementSchema.parse(raw);
}

export async function listProgress(): Promise<ProgressItem[]> {
  const raw = await apiJson<{ items: unknown[] }>("/api/progress");
  return z.array(progressItemSchema).parse(raw.items);
}

export async function fetchCatalogCc(): Promise<{
  exercises: CatalogCcExercise[];
}> {
  const raw = await apiJson<unknown>("/api/catalog/cc");
  const parsed = catalogCcResponseSchema.parse(raw);
  return {
    exercises: parsed.exercises.map((e) => ({
      schema_version: e.schema_version,
      id: e.id,
      slug: e.slug,
      name: e.name,
      description: e.description ?? null,
      exercise_type: e.exercise_type,
      steps: e.steps.map((s) => ({
        schema_version: s.schema_version,
        step_number: s.step_number,
        name: s.name,
        description: s.description,
        execution: s.execution ?? "",
        rationale: s.rationale ?? "",
        technique: s.technique ?? "",
        content_status: s.content_status,
        rules: s.rules as Record<string, unknown>,
      })),
    })),
  };
}

export async function overrideProgress(
  exerciseId: string,
  toStep: number,
  options?: { reason?: string; relatedOutcomeId?: string },
): Promise<{ progress: ProgressItem; event: ProgressionEvent }> {
  const raw = await apiJson<{ progress: unknown; event: unknown }>(
    `/api/progress/${exerciseId}/override`,
    {
      method: "POST",
      body: JSON.stringify({
        schema_version: 1,
        to_step: toStep,
        reason: options?.reason,
        related_outcome_id: options?.relatedOutcomeId ?? null,
      }),
    },
  );
  return {
    progress: progressItemSchema.parse(raw.progress),
    event: progressionEventSchema.parse(raw.event),
  };
}

export async function decideSatelliteRegression(
  exerciseId: string,
  recommendationId: string,
  decision: "accept" | "decline",
): Promise<{
  recommendationId: string;
  status: string;
  progress: ProgressItem;
  event: ProgressionEvent | null;
}> {
  const csrf = useAuthStore.getState().me?.csrf_token;
  const raw = await apiJson<{
    recommendation_id: string;
    status: string;
    progress: unknown;
    event: unknown | null;
  }>(
    `/api/satellites/${exerciseId}/regression-recommendations/${recommendationId}/${decision}`,
    {
      method: "POST",
      csrfToken: csrf,
      body: JSON.stringify({ schema_version: 1 }),
    },
  );
  return {
    recommendationId: raw.recommendation_id,
    status: raw.status,
    progress: progressItemSchema.parse(raw.progress),
    event: raw.event ? progressionEventSchema.parse(raw.event) : null,
  };
}
