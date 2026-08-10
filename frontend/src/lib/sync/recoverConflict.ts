/** FR-073a: recover losing_payload as a brand-new entity (never overwrite winner). */

import { acknowledgeConflict } from "@/lib/db/cache";
import { deleteOutboxItem, enqueueOutbox, listAllOutbox } from "@/lib/db/outbox";
import type { CachedConflict, OutboxEntityType } from "@/lib/db/types";
import { parseLosingPayload } from "@/lib/sync/conflictKind";
import { newClientMutationId } from "@/lib/uuid";

const RECOVERABLE: ReadonlySet<string> = new Set([
  "workout_session",
  "body_measurement",
]);

export type RecoverResult =
  | { ok: true; entityId: string; mutationId: string }
  | { ok: false; reason: "no_payload" | "delete_op" | "unsupported_entity" | "empty_payload" };

export function canRecoverConflict(conflict: CachedConflict): boolean {
  if (!RECOVERABLE.has(conflict.entity_type)) return false;
  const losing = parseLosingPayload(conflict.losing_payload);
  if (!losing) return false;
  if ((losing.op ?? "upsert") === "delete") return false;
  if (!losing.payload || typeof losing.payload !== "object") return false;
  return true;
}

export async function recoverConflictAsNewEntity(
  userId: string,
  conflict: CachedConflict,
): Promise<RecoverResult> {
  if (!RECOVERABLE.has(conflict.entity_type)) {
    return { ok: false, reason: "unsupported_entity" };
  }
  const losing = parseLosingPayload(conflict.losing_payload);
  if (!losing) return { ok: false, reason: "no_payload" };
  if ((losing.op ?? "upsert") === "delete") {
    return { ok: false, reason: "delete_op" };
  }
  const base = losing.payload;
  if (!base || typeof base !== "object") {
    return { ok: false, reason: "empty_payload" };
  }

  const mutationId = newClientMutationId();
  const entityId = newClientMutationId();
  const now = new Date().toISOString();
  const payload: Record<string, unknown> = {
    ...base,
    schema_version: typeof base.schema_version === "number" ? base.schema_version : 1,
    client_mutation_id: mutationId,
  };

  await enqueueOutbox(userId, {
    client_mutation_id: mutationId,
    entity_type: conflict.entity_type as OutboxEntityType,
    entity_id: entityId,
    op: "upsert",
    revision: 1,
    client_updated_at:
      typeof payload.performed_at === "string"
        ? payload.performed_at
        : typeof payload.measured_at === "string"
          ? payload.measured_at
          : now,
    payload,
    depends_on: [],
  });

  const all = await listAllOutbox(userId);
  for (const item of all) {
    if (
      item.status === "quarantine" &&
      (item.conflict_id === conflict.id || item.entity_id === conflict.entity_id)
    ) {
      await deleteOutboxItem(userId, item.client_mutation_id);
    }
  }

  await acknowledgeConflict(userId, conflict.id);
  return { ok: true, entityId, mutationId };
}
