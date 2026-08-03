/** Outbox sort FR-072a: stable topological order + type tie-breaker. */

import type { OutboxEntityType, OutboxItem } from "@/lib/db/types";

/** Independent items only — not a correctness source when depends_on is set. */
const TYPE_ORDER: Record<OutboxEntityType, number> = {
  legal_acceptance: 0,
  satellite: 1,
  workout_session: 2,
  body_measurement: 3,
};

function sortKeyTime(item: OutboxItem): string {
  const p = item.payload ?? {};
  if (item.entity_type === "workout_session") {
    return String(p.performed_at ?? item.client_updated_at);
  }
  if (item.entity_type === "body_measurement") {
    return String(p.measured_at ?? item.client_updated_at);
  }
  if (item.entity_type === "legal_acceptance") {
    return String(p.accepted_at ?? item.client_updated_at);
  }
  return String(p.client_updated_at ?? item.client_updated_at);
}

function tieBreak(a: OutboxItem, b: OutboxItem): number {
  const ta = TYPE_ORDER[a.entity_type];
  const tb = TYPE_ORDER[b.entity_type];
  if (ta !== tb) return ta - tb;

  const aDel = a.op === "delete" ? 0 : 1;
  const bDel = b.op === "delete" ? 0 : 1;
  if (aDel !== bDel) return aDel - bDel;

  const timeCmp = sortKeyTime(a).localeCompare(sortKeyTime(b));
  if (timeCmp !== 0) return timeCmp;
  const entityCmp = a.entity_id.localeCompare(b.entity_id);
  if (entityCmp !== 0) return entityCmp;
  return a.client_mutation_id.localeCompare(b.client_mutation_id);
}

export type TopoSortResult = {
  ordered: OutboxItem[];
  /** Mutation IDs participating in a cycle (excluded from ordered). */
  cycleIds: string[];
};

/**
 * Kahn topological sort over local depends_on edges.
 * Edges to mutation IDs absent from `items` are ignored (already synced / server-side).
 */
export function topologicalSortOutbox(items: OutboxItem[]): TopoSortResult {
  const byId = new Map(items.map((i) => [i.client_mutation_id, i]));
  const indegree = new Map<string, number>();
  const dependents = new Map<string, string[]>();

  for (const item of items) {
    indegree.set(item.client_mutation_id, 0);
    dependents.set(item.client_mutation_id, []);
  }

  for (const item of items) {
    for (const dep of item.depends_on ?? []) {
      if (!byId.has(dep)) continue;
      if (dep === item.client_mutation_id) continue;
      indegree.set(
        item.client_mutation_id,
        (indegree.get(item.client_mutation_id) ?? 0) + 1,
      );
      dependents.get(dep)!.push(item.client_mutation_id);
    }
  }

  const ready = items
    .filter((i) => (indegree.get(i.client_mutation_id) ?? 0) === 0)
    .sort(tieBreak);

  const ordered: OutboxItem[] = [];
  while (ready.length > 0) {
    const next = ready.shift()!;
    ordered.push(next);
    for (const childId of dependents.get(next.client_mutation_id) ?? []) {
      const nextDeg = (indegree.get(childId) ?? 0) - 1;
      indegree.set(childId, nextDeg);
      if (nextDeg === 0) {
        const child = byId.get(childId);
        if (child) {
          ready.push(child);
          ready.sort(tieBreak);
        }
      }
    }
  }

  const cycleIds = items
    .filter((i) => (indegree.get(i.client_mutation_id) ?? 0) > 0)
    .map((i) => i.client_mutation_id)
    .sort();

  return { ordered, cycleIds };
}

/** Stable order for flush listing; cyclic items are omitted (quarantine separately). */
export function sortOutboxItems(items: OutboxItem[]): OutboxItem[] {
  return topologicalSortOutbox(items).ordered;
}

export function takeFlushWindow(items: OutboxItem[], max = 20): OutboxItem[] {
  return sortOutboxItems(items).slice(0, max);
}
