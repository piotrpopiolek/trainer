import { apiJson } from "@/lib/api";
import {
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
import { newClientMutationId } from "@/lib/uuid";
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
    sets?: { schema_version: number; sets: Array<{ reps?: number }> };
    notes?: string;
    sort_order?: number;
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

export async function createSatellite(input: {
  name: string;
  exercise_type: "B" | "C";
  schedule_kind: "daily" | "weekdays" | "category";
  weekdays?: number[];
  schedule_category?: "anytime" | "post_workout" | "rest_day";
  goalReps: number;
  goalSets: number;
}): Promise<Satellite> {
  const raw = await apiJson<unknown>("/api/satellites", {
    method: "POST",
    body: JSON.stringify({
      schema_version: 1,
      name: input.name,
      exercise_type: input.exercise_type,
      active_metrics: { schema_version: 1, metrics: ["reps"] },
      schedule_kind: input.schedule_kind,
      weekdays: input.weekdays,
      schedule_category: input.schedule_category,
      steps: [
        {
          step_number: 1,
          name: "Goal",
          rules: {
            schema_version: 1,
            goal: {
              type: "reps",
              sets: input.goalSets,
              min_reps: input.goalReps,
            },
          },
        },
      ],
      client_mutation_id: newClientMutationId(),
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
  notes?: string;
}): Promise<Measurement> {
  const raw = await apiJson<unknown>("/api/measurements", {
    method: "POST",
    body: JSON.stringify({
      schema_version: 1,
      measured_at: input.measuredAt,
      local_date: input.localDate,
      metrics: {
        schema_version: 1,
        weight_kg: input.weightKg,
        waist_cm: input.waistCm,
        biceps_cm: input.bicepsCm,
      },
      notes: input.notes,
      client_mutation_id: newClientMutationId(),
    }),
  });
  return measurementSchema.parse(raw);
}

export async function overrideProgress(
  exerciseId: string,
  toStep: number,
  reason?: string,
): Promise<{ progress: ProgressItem; event: ProgressionEvent }> {
  const raw = await apiJson<{ progress: unknown; event: unknown }>(
    `/api/progress/${exerciseId}/override`,
    {
      method: "POST",
      body: JSON.stringify({
        schema_version: 1,
        to_step: toStep,
        reason,
      }),
    },
  );
  return {
    progress: progressItemSchema.parse(raw.progress),
    event: progressionEventSchema.parse(raw.event),
  };
}
