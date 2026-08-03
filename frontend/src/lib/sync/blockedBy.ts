/** FR-072b: local blocked_by / dependency_failed without a fifth outbox status. */

import type { OutboxItem } from "@/lib/db/types";

export type DependencyGate =
  | { kind: "ready"; blocked_by: [] }
  | { kind: "blocked"; blocked_by: string[] }
  | { kind: "failed"; blocked_by: string[] };

/**
 * Gate a flushable item against prerequisites still present in the outbox.
 *
 * - Absent dep → treated as already synced (server resolves missing).
 * - Dep in same flushable window → ready (topo orders the batch).
 * - Dep quarantine → failed (`dependency_failed`).
 * - Dep still pending/in_flight but not flushable yet → blocked (no attempt).
 */
export function gateItemByDependencies(
  item: OutboxItem,
  opts: {
    outboxById: Map<string, OutboxItem>;
    flushableIds: Set<string>;
  },
): DependencyGate {
  const blocked: string[] = [];
  const failed: string[] = [];
  for (const dep of item.depends_on ?? []) {
    const prereq = opts.outboxById.get(dep);
    if (!prereq) continue;
    if (prereq.status === "quarantine") {
      failed.push(dep);
      continue;
    }
    if (!opts.flushableIds.has(dep)) {
      blocked.push(dep);
    }
  }
  if (failed.length > 0) {
    return { kind: "failed", blocked_by: [...failed].sort() };
  }
  if (blocked.length > 0) {
    return { kind: "blocked", blocked_by: [...blocked].sort() };
  }
  return { kind: "ready", blocked_by: [] };
}
