import { describe, expect, it } from "vitest";

import { gateItemByDependencies } from "@/lib/sync/blockedBy";
import type { OutboxItem } from "@/lib/db/types";

function item(
  partial: Partial<OutboxItem> &
    Pick<OutboxItem, "client_mutation_id" | "entity_type" | "entity_id" | "op">,
): OutboxItem {
  return {
    schema_version: 1,
    revision: 1,
    client_updated_at: "2026-08-03T10:00:00.000Z",
    payload: null,
    depends_on: [],
    blocked_by: [],
    status: "pending",
    attempts: 0,
    transport_failures: 0,
    next_attempt_at: null,
    last_error_code: null,
    conflict_id: null,
    created_at: "2026-08-03T10:00:00.000Z",
    updated_at: "2026-08-03T10:00:00.000Z",
    ...partial,
  };
}

describe("gateItemByDependencies (FR-072b)", () => {
  const legal = "018f0000-0000-7000-8000-0000000000a1";
  const session = "018f0000-0000-7000-8000-0000000000a2";

  it("blocks when prereq is pending but not flushable (backoff)", () => {
    const prereq = item({
      client_mutation_id: legal,
      entity_type: "legal_acceptance",
      entity_id: "018f0000-0000-7000-8000-0000000000c1",
      op: "upsert",
      status: "pending",
      next_attempt_at: "2099-01-01T00:00:00.000Z",
    });
    const dependent = item({
      client_mutation_id: session,
      entity_type: "workout_session",
      entity_id: "018f0000-0000-7000-8000-0000000000d1",
      op: "upsert",
      depends_on: [legal],
    });
    const outboxById = new Map([
      [legal, prereq],
      [session, dependent],
    ]);
    const gate = gateItemByDependencies(dependent, {
      outboxById,
      flushableIds: new Set([session]),
    });
    expect(gate).toEqual({ kind: "blocked", blocked_by: [legal] });
  });

  it("fails when prereq is quarantined", () => {
    const prereq = item({
      client_mutation_id: legal,
      entity_type: "legal_acceptance",
      entity_id: "018f0000-0000-7000-8000-0000000000c1",
      op: "upsert",
      status: "quarantine",
      last_error_code: "legal_required",
    });
    const dependent = item({
      client_mutation_id: session,
      entity_type: "workout_session",
      entity_id: "018f0000-0000-7000-8000-0000000000d1",
      op: "upsert",
      depends_on: [legal],
    });
    const gate = gateItemByDependencies(dependent, {
      outboxById: new Map([
        [legal, prereq],
        [session, dependent],
      ]),
      flushableIds: new Set([session]),
    });
    expect(gate).toEqual({ kind: "failed", blocked_by: [legal] });
  });

  it("is ready when prereq is in the same flushable set", () => {
    const prereq = item({
      client_mutation_id: legal,
      entity_type: "legal_acceptance",
      entity_id: "018f0000-0000-7000-8000-0000000000c1",
      op: "upsert",
    });
    const dependent = item({
      client_mutation_id: session,
      entity_type: "workout_session",
      entity_id: "018f0000-0000-7000-8000-0000000000d1",
      op: "upsert",
      depends_on: [legal],
    });
    const gate = gateItemByDependencies(dependent, {
      outboxById: new Map([
        [legal, prereq],
        [session, dependent],
      ]),
      flushableIds: new Set([legal, session]),
    });
    expect(gate).toEqual({ kind: "ready", blocked_by: [] });
  });

  it("is ready when prereq is absent from outbox (already synced)", () => {
    const dependent = item({
      client_mutation_id: session,
      entity_type: "workout_session",
      entity_id: "018f0000-0000-7000-8000-0000000000d1",
      op: "upsert",
      depends_on: [legal],
    });
    const gate = gateItemByDependencies(dependent, {
      outboxById: new Map([[session, dependent]]),
      flushableIds: new Set([session]),
    });
    expect(gate).toEqual({ kind: "ready", blocked_by: [] });
  });
});
