/** Outbox sort (FR-072a) + soft-delete before upsert in session segment. */

import type { OutboxEntityType, OutboxItem } from "@/lib/db/types";

const TYPE_ORDER: Record<OutboxEntityType, number> = {
  legal_acceptance: 0,
  workout_session: 1,
  body_measurement: 2,
  satellite: 3,
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

/**
 * Sort pending outbox for push: legal → sessions → measurements → satellites;
 * within type delete before upsert; then time + entity_id.
 */
export function sortOutboxItems(items: OutboxItem[]): OutboxItem[] {
  const copy = [...items];
  copy.sort((a, b) => {
    const ta = TYPE_ORDER[a.entity_type];
    const tb = TYPE_ORDER[b.entity_type];
    if (ta !== tb) return ta - tb;

    const aDel = a.op === "delete" ? 0 : 1;
    const bDel = b.op === "delete" ? 0 : 1;
    if (aDel !== bDel) return aDel - bDel;

    const timeCmp = sortKeyTime(a).localeCompare(sortKeyTime(b));
    if (timeCmp !== 0) return timeCmp;
    return a.entity_id.localeCompare(b.entity_id);
  });
  return copy;
}

export function takeFlushWindow(items: OutboxItem[], max = 20): OutboxItem[] {
  return sortOutboxItems(items).slice(0, max);
}
