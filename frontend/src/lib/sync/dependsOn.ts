/** Pure helpers for outbox depends_on edges (FR-072a / Stage 2 Slice D). */

import type { OutboxItem } from "@/lib/db/types";

export type SessionLogRef = {
  exercise_id: string;
  exercise_kind: "cc" | "satellite";
};

/**
 * Collect mutation IDs that a session upsert must wait on:
 * pending legal, pending satellite creates for logged exercises,
 * and pending session deletes for the same local_date (tombstone→replacement).
 */
export function resolveSessionDependsOn(opts: {
  pending: OutboxItem[];
  localDate: string;
  logs: SessionLogRef[];
  extraDependsOn?: string[];
}): string[] {
  const deps = new Set(opts.extraDependsOn ?? []);
  const satExerciseIds = new Set(
    opts.logs
      .filter((l) => l.exercise_kind === "satellite")
      .map((l) => l.exercise_id),
  );

  for (const item of opts.pending) {
    if (item.status !== "pending" && item.status !== "in_flight") continue;

    if (item.entity_type === "legal_acceptance") {
      deps.add(item.client_mutation_id);
      continue;
    }

    if (
      item.entity_type === "satellite" &&
      item.op === "upsert" &&
      satExerciseIds.has(item.entity_id)
    ) {
      deps.add(item.client_mutation_id);
      continue;
    }

    if (item.entity_type === "workout_session" && item.op === "delete") {
      const tombstoneDate =
        item.payload && typeof item.payload.local_date === "string"
          ? item.payload.local_date
          : null;
      if (tombstoneDate === opts.localDate) {
        deps.add(item.client_mutation_id);
      }
    }
  }

  return [...deps].sort();
}
