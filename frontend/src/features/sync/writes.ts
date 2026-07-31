import { ApiError } from "@/lib/api";
import {
  deleteSessionCache,
  putMeasurementCache,
  putSatelliteCache,
  putSessionCache,
} from "@/lib/db/cache";
import { enqueueOutbox } from "@/lib/db/outbox";
import { requestPersistentStorage } from "@/lib/db/persist";
import type { Measurement, Satellite, Session } from "@/lib/schemas";
import { newClientMutationId } from "@/lib/uuid";
import { useSyncStore } from "@/stores/syncStore";
import { flushOutbox } from "@/features/sync/flush";
import * as online from "@/features/training/api";

function isOfflineOrNetwork(err: unknown): boolean {
  if (typeof navigator !== "undefined" && !navigator.onLine) return true;
  if (err instanceof TypeError) return true;
  if (err instanceof ApiError) {
    if (err.status === 0 || err.status >= 500) return true;
    if (err.status === 408 || err.status === 429) return true;
  }
  return false;
}

async function afterEnqueue(userId: string): Promise<void> {
  await requestPersistentStorage(userId);
  await useSyncStore.getState().refresh();
  if (navigator.onLine) {
    const result = await flushOutbox(userId);
    if (result.progressionEvents.length) {
      useSyncStore.getState().pushEvents(result.progressionEvents);
    }
    await useSyncStore.getState().refresh();
  }
}

export async function createSessionOfflineAware(
  userId: string,
  input: Parameters<typeof online.createSession>[0],
): Promise<{ session: Session; pendingSync: boolean }> {
  if (navigator.onLine) {
    try {
      const session = await online.createSession(input);
      await putSessionCache(userId, session as unknown as Record<string, unknown>);
      return { session, pendingSync: false };
    } catch (err) {
      if (!isOfflineOrNetwork(err)) throw err;
    }
  }

  const mutationId = newClientMutationId();
  const entityId = newClientMutationId();
  const now = new Date().toISOString();
  const payload = {
    schema_version: 1,
    performed_at: input.performedAt,
    local_date: input.localDate,
    client_mutation_id: mutationId,
    client_timezone: input.clientTimezone,
    notes: input.notes,
    logs: input.logs,
  };
  await enqueueOutbox(userId, {
    client_mutation_id: mutationId,
    entity_type: "workout_session",
    entity_id: entityId,
    op: "upsert",
    revision: 1,
    client_updated_at: input.performedAt,
    payload,
  });
  const session: Session = {
    schema_version: 1,
    id: entityId,
    performed_at: input.performedAt,
    local_date: input.localDate,
    notes: input.notes ?? null,
    revision: 1,
    deleted_at: null,
    logs: input.logs.map((l) => ({
      schema_version: 1,
      id: newClientMutationId(),
      exercise_id: l.exercise_id,
      exercise_kind: l.exercise_kind,
      section: l.section ?? "main",
      exercise_name_snapshot: l.exercise_id.slice(0, 8),
      skipped: l.skipped ?? false,
      sets: l.sets,
      goal_met: false,
      counts_for_progression: false,
      notes: l.notes ?? null,
    })),
    progression_events: [],
    progress: [],
  };
  await putSessionCache(userId, {
    ...session,
    pending_sync: true,
    updated_at: now,
  } as unknown as Record<string, unknown>);
  await afterEnqueue(userId);
  return { session, pendingSync: true };
}

export async function softDeleteSessionOfflineAware(
  userId: string,
  sessionId: string,
  revision: number,
): Promise<{ pendingSync: boolean }> {
  if (navigator.onLine) {
    try {
      await online.softDeleteSession(sessionId);
      await deleteSessionCache(userId, sessionId);
      return { pendingSync: false };
    } catch (err) {
      if (!isOfflineOrNetwork(err)) throw err;
    }
  }
  await enqueueOutbox(userId, {
    entity_type: "workout_session",
    entity_id: sessionId,
    op: "delete",
    revision: revision + 1,
    payload: null,
  });
  await deleteSessionCache(userId, sessionId);
  await afterEnqueue(userId);
  return { pendingSync: true };
}

export async function createMeasurementOfflineAware(
  userId: string,
  input: Parameters<typeof online.createMeasurement>[0],
): Promise<{ measurement: Measurement; pendingSync: boolean }> {
  if (navigator.onLine) {
    try {
      const measurement = await online.createMeasurement(input);
      await putMeasurementCache(userId, measurement as unknown as Record<string, unknown>);
      return { measurement, pendingSync: false };
    } catch (err) {
      if (!isOfflineOrNetwork(err)) throw err;
    }
  }
  const mutationId = newClientMutationId();
  const entityId = newClientMutationId();
  const payload = {
    schema_version: 1,
    measured_at: input.measuredAt,
    local_date: input.localDate,
    metrics: {
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
    },
    notes: input.notes,
    client_mutation_id: mutationId,
  };
  await enqueueOutbox(userId, {
    client_mutation_id: mutationId,
    entity_type: "body_measurement",
    entity_id: entityId,
    revision: 1,
    client_updated_at: input.measuredAt,
    payload,
  });
  const measurement: Measurement = {
    schema_version: 1,
    id: entityId,
    measured_at: input.measuredAt,
    local_date: input.localDate,
    metrics: payload.metrics,
    notes: input.notes ?? null,
    revision: 1,
  };
  await putMeasurementCache(userId, measurement as unknown as Record<string, unknown>);
  await afterEnqueue(userId);
  return { measurement, pendingSync: true };
}

export async function createSatelliteOfflineAware(
  userId: string,
  input: Parameters<typeof online.createSatellite>[0],
): Promise<{ satellite: Satellite; pendingSync: boolean }> {
  if (navigator.onLine) {
    try {
      const satellite = await online.createSatellite(input);
      await putSatelliteCache(userId, satellite as unknown as Record<string, unknown>);
      return { satellite, pendingSync: false };
    } catch (err) {
      if (!isOfflineOrNetwork(err)) throw err;
    }
  }
  const mutationId = newClientMutationId();
  const entityId = newClientMutationId();
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
  const payload = {
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
    client_mutation_id: mutationId,
  };
  await enqueueOutbox(userId, {
    client_mutation_id: mutationId,
    entity_type: "satellite",
    entity_id: entityId,
    revision: 1,
    payload,
  });
  const satellite: Satellite = {
    schema_version: 1,
    id: entityId,
    name: input.name,
    exercise_type: input.exercise_type,
    active_metrics: payload.active_metrics,
    schedule_kind: input.schedule_kind,
    weekdays: input.weekdays ?? null,
    schedule_category: input.schedule_category ?? null,
    revision: 1,
    current_config_version_id: null,
    config_hash: null,
    steps: payload.steps as unknown as Array<Record<string, unknown>>,
  };
  await putSatelliteCache(userId, satellite as unknown as Record<string, unknown>);
  await afterEnqueue(userId);
  return { satellite, pendingSync: true };
}

export async function enqueueLegalAcceptance(
  userId: string,
  payload: Record<string, unknown>,
): Promise<void> {
  const mutationId =
    typeof payload.client_mutation_id === "string"
      ? payload.client_mutation_id
      : newClientMutationId();
  const entityId =
    typeof payload.document_id === "string" ? payload.document_id : mutationId;
  await enqueueOutbox(userId, {
    client_mutation_id: mutationId,
    entity_type: "legal_acceptance",
    entity_id: entityId,
    revision: 1,
    client_updated_at:
      typeof payload.accepted_at === "string"
        ? payload.accepted_at
        : new Date().toISOString(),
    payload: { ...payload, client_mutation_id: mutationId },
  });
  await afterEnqueue(userId);
}
