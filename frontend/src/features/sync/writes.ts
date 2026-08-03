import { ApiError } from "@/lib/api";
import {
  deleteSessionCache,
  putMeasurementCache,
  putSatelliteCache,
  putSessionCache,
} from "@/lib/db/cache";
import { enqueueOutbox, listOutboxByStatus } from "@/lib/db/outbox";
import { openUserDb } from "@/lib/db/open";
import { requestPersistentStorage } from "@/lib/db/persist";
import { buildOfflineSatellitePin } from "@/lib/satelliteOfflinePin";
import type { Measurement, ProgressionEvent, Satellite, Session } from "@/lib/schemas";
import { resolveSessionDependsOn } from "@/lib/sync/dependsOn";
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

export type CreateSessionOfflineOptions = {
  /** Extra mutation IDs (e.g. explicit tombstone when not discoverable). */
  dependsOn?: string[];
};

export async function createSessionOfflineAware(
  userId: string,
  input: Parameters<typeof online.createSession>[0],
  options?: CreateSessionOfflineOptions,
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
  const pending = await listOutboxByStatus(userId, ["pending", "in_flight"]);
  const dependsOn = resolveSessionDependsOn({
    pending,
    localDate: input.localDate,
    logs: input.logs,
    extraDependsOn: options?.dependsOn,
  });
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
    depends_on: dependsOn,
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
      satellite_config_version_id: l.satellite_config_version_id ?? null,
      satellite_config_hash: l.satellite_config_hash ?? null,
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
): Promise<{ pendingSync: boolean; clientMutationId: string }> {
  if (navigator.onLine) {
    try {
      await online.softDeleteSession(sessionId);
      await deleteSessionCache(userId, sessionId);
      return { pendingSync: false, clientMutationId: "" };
    } catch (err) {
      if (!isOfflineOrNetwork(err)) throw err;
    }
  }

  let localDate: string | null = null;
  try {
    const db = await openUserDb(userId);
    const cached = await db.get("sessions", sessionId);
    if (cached && typeof cached.local_date === "string") {
      localDate = cached.local_date;
    }
  } catch {
    // cache miss is fine — replacement edge may be passed explicitly
  }

  const mutationId = newClientMutationId();
  await enqueueOutbox(userId, {
    client_mutation_id: mutationId,
    entity_type: "workout_session",
    entity_id: sessionId,
    op: "delete",
    revision: revision + 1,
    payload: localDate ? { local_date: localDate } : null,
  });
  await deleteSessionCache(userId, sessionId);
  await afterEnqueue(userId);
  return { pendingSync: true, clientMutationId: mutationId };
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
  const pin = await buildOfflineSatellitePin({
    exercise_type: input.exercise_type,
    stepName: input.stepName,
    goalSets: input.goalSets,
    goalReps: input.goalReps,
    requireBothSides: input.requireBothSides,
    trackWeight: input.trackWeight,
  });
  const payload = {
    schema_version: 1,
    name: input.name,
    exercise_type: input.exercise_type,
    active_metrics: pin.activeMetrics,
    schedule_kind: input.schedule_kind,
    weekdays: input.weekdays,
    schedule_category: input.schedule_category,
    config_version_id: pin.configVersionId,
    steps: pin.steps.map((s) => ({
      step_number: s.step_number,
      step_id: s.step_id,
      name: s.name,
      rules: s.rules,
    })),
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
    active_metrics: pin.activeMetrics,
    schedule_kind: input.schedule_kind,
    weekdays: input.weekdays ?? null,
    schedule_category: input.schedule_category ?? null,
    revision: 1,
    current_config_version_id: pin.configVersionId,
    config_hash: pin.configHash,
    steps: pin.steps.map((s) => ({
      step_number: s.step_number,
      step_id: s.step_id,
      name: s.name,
      rules: s.rules,
    })) as unknown as Array<Record<string, unknown>>,
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

export async function decideSatelliteRegressionOfflineAware(
  userId: string,
  input: {
    exerciseId: string;
    recommendationId: string;
    decision: "accept" | "decline";
  },
): Promise<{ pendingSync: boolean; event: ProgressionEvent | null }> {
  if (navigator.onLine) {
    try {
      const result = await online.decideSatelliteRegression(
        input.exerciseId,
        input.recommendationId,
        input.decision,
      );
      return { pendingSync: false, event: result.event };
    } catch (err) {
      if (!isOfflineOrNetwork(err)) throw err;
    }
  }

  const mutationId = newClientMutationId();
  const now = new Date().toISOString();
  await enqueueOutbox(userId, {
    client_mutation_id: mutationId,
    entity_type: "satellite_regression_decision",
    entity_id: input.exerciseId,
    revision: 1,
    client_updated_at: now,
    payload: {
      schema_version: 1,
      recommendation_id: input.recommendationId,
      decision: input.decision,
      client_mutation_id: mutationId,
    },
  });
  await afterEnqueue(userId);
  return { pendingSync: true, event: null };
}
