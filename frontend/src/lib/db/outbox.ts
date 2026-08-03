import { openUserDb } from "@/lib/db/open";
import type { OutboxEntityType, OutboxItem, OutboxOp, OutboxStatus } from "@/lib/db/types";
import { newClientMutationId } from "@/lib/uuid";

export type EnqueueInput = {
  entity_type: OutboxEntityType;
  entity_id: string;
  op?: OutboxOp;
  revision?: number;
  client_updated_at?: string;
  payload: Record<string, unknown> | null;
  client_mutation_id?: string;
  depends_on?: string[];
};

export async function enqueueOutbox(
  userId: string,
  input: EnqueueInput,
): Promise<OutboxItem> {
  const now = new Date().toISOString();
  const dependsOn = [...new Set(input.depends_on ?? [])].sort();
  const item: OutboxItem = {
    schema_version: 1,
    client_mutation_id: input.client_mutation_id ?? newClientMutationId(),
    entity_type: input.entity_type,
    entity_id: input.entity_id,
    op: input.op ?? "upsert",
    revision: input.revision ?? 1,
    client_updated_at: input.client_updated_at ?? now,
    payload: input.payload,
    depends_on: dependsOn,
    blocked_by: [],
    status: "pending",
    attempts: 0,
    transport_failures: 0,
    next_attempt_at: null,
    last_error_code: null,
    conflict_id: null,
    created_at: now,
    updated_at: now,
  };
  const db = await openUserDb(userId);
  await db.put("outbox", item);
  return item;
}

export async function listOutboxByStatus(
  userId: string,
  statuses: OutboxStatus[],
): Promise<OutboxItem[]> {
  const db = await openUserDb(userId);
  const all = await db.getAll("outbox");
  return all.filter((i) => statuses.includes(i.status));
}

export async function listFlushableOutbox(userId: string, now = new Date()): Promise<OutboxItem[]> {
  const items = await listOutboxByStatus(userId, ["pending"]);
  const iso = now.toISOString();
  // Unsorted: flush runs topologicalSortOutbox (cycles must remain visible).
  return items.filter((i) => i.next_attempt_at == null || i.next_attempt_at <= iso);
}

export async function updateOutboxItem(
  userId: string,
  item: OutboxItem,
): Promise<void> {
  const db = await openUserDb(userId);
  await db.put("outbox", { ...item, updated_at: new Date().toISOString() });
}

export async function deleteOutboxItem(
  userId: string,
  clientMutationId: string,
): Promise<void> {
  const db = await openUserDb(userId);
  await db.delete("outbox", clientMutationId);
}

export async function outboxCounts(userId: string): Promise<{
  pending: number;
  in_flight: number;
  quarantine: number;
  oldestPendingAt: string | null;
}> {
  const db = await openUserDb(userId);
  const all = await db.getAll("outbox");
  let pending = 0;
  let in_flight = 0;
  let quarantine = 0;
  let oldestPendingAt: string | null = null;
  for (const i of all) {
    if (i.status === "pending") {
      pending += 1;
      if (!oldestPendingAt || i.created_at < oldestPendingAt) {
        oldestPendingAt = i.created_at;
      }
    } else if (i.status === "in_flight") {
      in_flight += 1;
    } else if (i.status === "quarantine") {
      quarantine += 1;
    }
  }
  return { pending, in_flight, quarantine, oldestPendingAt };
}

export async function resetInFlightToPending(userId: string): Promise<void> {
  const db = await openUserDb(userId);
  const all = await db.getAll("outbox");
  for (const item of all) {
    if (item.status === "in_flight") {
      await db.put("outbox", {
        ...item,
        status: "pending",
        updated_at: new Date().toISOString(),
      });
    }
  }
}
