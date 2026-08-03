import {
  applyTombstone,
  putMeasurementCache,
  putProgressCache,
  putSatelliteCache,
  putSessionCache,
  replaceProgressCache,
  upsertConflict,
} from "@/lib/db/cache";
import { getLastPullServerTime, getOrCreateDeviceId, setLastPullServerTime } from "@/lib/db/meta";
import {
  deleteOutboxItem,
  listFlushableOutbox,
  resetInFlightToPending,
  updateOutboxItem,
} from "@/lib/db/outbox";
import { classifyAck, nextAttemptAtIso, type PushItemStatus } from "@/lib/sync/classify";
import { takeFlushWindow, topologicalSortOutbox } from "@/lib/sync/sort";
import { syncPull, syncPush, type SyncPushResponse } from "@/features/sync/api";
import { ApiError } from "@/lib/api";
import { progressionEventSchema, type ProgressionEvent } from "@/lib/schemas";

/** Pure helper — map sync push ACKs by mutation ID (FR-072a). */
export function indexPushResultsByMutationId(
  results: SyncPushResponse["results"],
): Map<string, SyncPushResponse["results"][number]> {
  return new Map(results.map((r) => [r.client_mutation_id, r]));
}

export type FlushResult = {
  pushed: number;
  done: number;
  quarantined: number;
  conflicts: number;
  transportFailures: number;
  progressionEvents: ProgressionEvent[];
  truncated: boolean;
};

let flushMutex: Promise<FlushResult> | null = null;

export async function applyPull(userId: string, locale?: string): Promise<void> {
  const deviceId = await getOrCreateDeviceId(userId);
  const since = await getLastPullServerTime(userId);
  const pull = await syncPull({ since, locale, deviceId });

  const full = !since || pull.resync_required;
  for (const s of pull.sessions) {
    if (s.id) await putSessionCache(userId, s);
  }
  for (const m of pull.measurements) {
    if (m.id) await putMeasurementCache(userId, m);
  }
  for (const sat of pull.satellites) {
    if (sat.id) await putSatelliteCache(userId, sat);
  }
  if (full) {
    await replaceProgressCache(userId, pull.progress);
  } else if (pull.progress.length) {
    await putProgressCache(userId, pull.progress);
  }
  for (const t of pull.tombstones) {
    await applyTombstone(userId, t.entity_type, t.id);
  }
  for (const c of pull.conflicts) {
    if (typeof c.id === "string") {
      await upsertConflict(userId, {
        id: c.id,
        entity_type: String(c.entity_type ?? ""),
        entity_id: String(c.entity_id ?? ""),
        conflict_kind: String(c.conflict_kind ?? ""),
        created_at: String(c.created_at ?? new Date().toISOString()),
        acknowledged: false,
      });
    }
  }
  await setLastPullServerTime(userId, pull.server_time);
}

async function applyPushResults(
  userId: string,
  windowItems: Awaited<ReturnType<typeof listFlushableOutbox>>,
  response: SyncPushResponse,
): Promise<Omit<FlushResult, "pushed" | "truncated">> {
  let done = 0;
  let quarantined = 0;
  let conflicts = 0;
  const progressionEvents: ProgressionEvent[] = [];

  // FR-072a/d: ACK by client_mutation_id — never by array index (server may reorder).
  const byMutationId = indexPushResultsByMutationId(response.results);

  for (const item of windowItems) {
    const result = byMutationId.get(item.client_mutation_id);
    if (!result) {
      // truncated / missing result → pending; do not bump attempts
      item.status = "pending";
      await updateOutboxItem(userId, item);
      continue;
    }
    const action = classifyAck(
      result.status as PushItemStatus,
      result.error_code ?? null,
    );
    if (action.kind === "done") {
      await deleteOutboxItem(userId, item.client_mutation_id);
      done += 1;
    } else if (action.kind === "conflict") {
      conflicts += 1;
      item.status = "quarantine";
      item.last_error_code = result.status;
      item.conflict_id = result.conflict_id ?? null;
      await updateOutboxItem(userId, item);
      if (result.conflict_id) {
        await upsertConflict(userId, {
          id: result.conflict_id,
          entity_type: item.entity_type,
          entity_id: item.entity_id,
          conflict_kind: result.status,
          created_at: new Date().toISOString(),
          acknowledged: false,
          winning_revision: result.winning_revision,
        });
      }
    } else if (action.kind === "quarantine") {
      quarantined += 1;
      item.status = "quarantine";
      item.last_error_code = action.errorCode;
      await updateOutboxItem(userId, item);
    } else {
      item.status = "pending";
      item.attempts += 1;
      item.last_error_code = action.errorCode;
      item.next_attempt_at = nextAttemptAtIso(item.attempts);
      await updateOutboxItem(userId, item);
    }
  }

  for (const ev of response.progression_events) {
    const parsed = progressionEventSchema.safeParse(ev);
    if (parsed.success) progressionEvents.push(parsed.data);
  }
  if (response.progress.length) {
    await putProgressCache(userId, response.progress);
  }

  return { done, quarantined, conflicts, transportFailures: 0, progressionEvents };
}

export async function flushOutbox(userId: string): Promise<FlushResult> {
  if (flushMutex) return flushMutex;

  flushMutex = (async () => {
    await resetInFlightToPending(userId);
    const empty: FlushResult = {
      pushed: 0,
      done: 0,
      quarantined: 0,
      conflicts: 0,
      transportFailures: 0,
      progressionEvents: [],
      truncated: false,
    };
    let aggregate = { ...empty };
    const deviceId = await getOrCreateDeviceId(userId);

    // Loop batches until empty / truncated stop / auth
    for (let round = 0; round < 10; round += 1) {
      const ready = await listFlushableOutbox(userId);
      if (ready.length === 0) break;

      const { ordered, cycleIds } = topologicalSortOutbox(ready);
      for (const cycleId of cycleIds) {
        const item = ready.find((i) => i.client_mutation_id === cycleId);
        if (!item) continue;
        item.status = "quarantine";
        item.last_error_code = "dependency_cycle";
        item.blocked_by = [...(item.depends_on ?? [])];
        await updateOutboxItem(userId, item);
        aggregate.quarantined += 1;
      }
      if (ordered.length === 0) break;

      const window = takeFlushWindow(ordered, 20);

      for (const item of window) {
        item.status = "in_flight";
        await updateOutboxItem(userId, item);
      }

      try {
        const response = await syncPush(
          window.map((i) => ({
            client_mutation_id: i.client_mutation_id,
            entity_type: i.entity_type,
            entity_id: i.entity_id,
            op: i.op,
            revision: i.revision,
            client_updated_at: i.client_updated_at,
            payload: i.payload,
            depends_on: i.depends_on ?? [],
          })),
          deviceId,
        );
        const applied = await applyPushResults(userId, window, response);
        aggregate = {
          pushed: aggregate.pushed + window.length,
          done: aggregate.done + applied.done,
          quarantined: aggregate.quarantined + applied.quarantined,
          conflicts: aggregate.conflicts + applied.conflicts,
          transportFailures: aggregate.transportFailures,
          progressionEvents: [
            ...aggregate.progressionEvents,
            ...applied.progressionEvents,
          ],
          truncated: response.truncated,
        };
        // Incremental pull after successful push
        try {
          await applyPull(userId);
        } catch {
          // pull failure shouldn't drop push ACKs
        }
        if (!response.truncated) {
          // continue if more pending
          continue;
        }
        break;
      } catch (err) {
        for (const item of window) {
          item.status = "pending";
          item.transport_failures += 1;
          item.attempts += 1;
          item.next_attempt_at = nextAttemptAtIso(item.attempts);
          item.last_error_code =
            err instanceof ApiError ? err.errorCode : "transport_error";
          await updateOutboxItem(userId, item);
        }
        aggregate.transportFailures += 1;
        if (err instanceof ApiError && err.status === 401) {
          break;
        }
        break;
      }
    }
    return aggregate;
  })();

  try {
    return await flushMutex;
  } finally {
    flushMutex = null;
  }
}
