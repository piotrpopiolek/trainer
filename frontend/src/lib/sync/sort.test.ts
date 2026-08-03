import { describe, expect, it } from "vitest";

import { classifyAck, nextBackoffMs } from "@/lib/sync/classify";
import {
  sortOutboxItems,
  takeFlushWindow,
  topologicalSortOutbox,
} from "@/lib/sync/sort";
import type { OutboxItem } from "@/lib/db/types";

function item(
  partial: Partial<OutboxItem> &
    Pick<OutboxItem, "client_mutation_id" | "entity_type" | "entity_id" | "op">,
): OutboxItem {
  return {
    schema_version: 1,
    revision: 1,
    client_updated_at: "2026-07-28T10:00:00.000Z",
    payload: null,
    depends_on: [],
    blocked_by: [],
    status: "pending",
    attempts: 0,
    transport_failures: 0,
    next_attempt_at: null,
    last_error_code: null,
    conflict_id: null,
    created_at: "2026-07-28T10:00:00.000Z",
    updated_at: "2026-07-28T10:00:00.000Z",
    ...partial,
  };
}

describe("outbox sort FR-072a (topo + tie-breaker)", () => {
  it("tie-breaks legal → satellite → session → measurement; deletes before upserts", () => {
    const sorted = sortOutboxItems([
      item({
        client_mutation_id: "018f0000-0000-7000-8000-000000000004",
        entity_type: "satellite",
        entity_id: "018f0000-0000-7000-8000-000000000014",
        op: "upsert",
      }),
      item({
        client_mutation_id: "018f0000-0000-7000-8000-000000000001",
        entity_type: "workout_session",
        entity_id: "018f0000-0000-7000-8000-000000000011",
        op: "upsert",
        payload: { performed_at: "2026-07-28T12:00:00.000Z", local_date: "2026-07-28" },
      }),
      item({
        client_mutation_id: "018f0000-0000-7000-8000-000000000003",
        entity_type: "body_measurement",
        entity_id: "018f0000-0000-7000-8000-000000000013",
        op: "upsert",
        payload: { measured_at: "2026-07-28T11:00:00.000Z" },
      }),
      item({
        client_mutation_id: "018f0000-0000-7000-8000-000000000000",
        entity_type: "legal_acceptance",
        entity_id: "018f0000-0000-7000-8000-000000000010",
        op: "upsert",
        payload: { accepted_at: "2026-07-28T09:00:00.000Z" },
      }),
      item({
        client_mutation_id: "018f0000-0000-7000-8000-000000000002",
        entity_type: "workout_session",
        entity_id: "018f0000-0000-7000-8000-000000000012",
        op: "delete",
        client_updated_at: "2026-07-28T11:30:00.000Z",
      }),
    ]);

    expect(sorted.map((i) => i.entity_type)).toEqual([
      "legal_acceptance",
      "satellite",
      "workout_session",
      "workout_session",
      "body_measurement",
    ]);
    expect(sorted[2]?.op).toBe("delete");
    expect(sorted[3]?.op).toBe("upsert");
  });

  it("orders by depends_on even when it reverses type tie-breaker", () => {
    const meas = "018f0000-0000-7000-8000-0000000000aa";
    const sat = "018f0000-0000-7000-8000-0000000000bb";
    const sorted = sortOutboxItems([
      item({
        client_mutation_id: sat,
        entity_type: "satellite",
        entity_id: "018f0000-0000-7000-8000-000000000014",
        op: "upsert",
        depends_on: [meas],
      }),
      item({
        client_mutation_id: meas,
        entity_type: "body_measurement",
        entity_id: "018f0000-0000-7000-8000-000000000013",
        op: "upsert",
        payload: { measured_at: "2026-07-28T11:00:00.000Z" },
      }),
    ]);
    expect(sorted.map((i) => i.client_mutation_id)).toEqual([meas, sat]);
  });

  it("detects cycles and excludes them from ordered", () => {
    const a = "018f0000-0000-7000-8000-0000000000a1";
    const b = "018f0000-0000-7000-8000-0000000000b1";
    const legal = "018f0000-0000-7000-8000-0000000000c1";
    const result = topologicalSortOutbox([
      item({
        client_mutation_id: a,
        entity_type: "workout_session",
        entity_id: "018f0000-0000-7000-8000-000000000011",
        op: "upsert",
        depends_on: [b],
      }),
      item({
        client_mutation_id: b,
        entity_type: "workout_session",
        entity_id: "018f0000-0000-7000-8000-000000000012",
        op: "upsert",
        depends_on: [a],
      }),
      item({
        client_mutation_id: legal,
        entity_type: "legal_acceptance",
        entity_id: "018f0000-0000-7000-8000-000000000010",
        op: "upsert",
      }),
    ]);
    expect(result.ordered.map((i) => i.client_mutation_id)).toEqual([legal]);
    expect(result.cycleIds.sort()).toEqual([a, b].sort());
  });

  it("ignores depends_on pointing outside the queue", () => {
    const sorted = sortOutboxItems([
      item({
        client_mutation_id: "018f0000-0000-7000-8000-000000000001",
        entity_type: "workout_session",
        entity_id: "018f0000-0000-7000-8000-000000000011",
        op: "upsert",
        depends_on: ["018f0000-0000-7000-8000-00000000dead"],
      }),
    ]);
    expect(sorted).toHaveLength(1);
  });

  it("uses client_updated_at when payload times missing", () => {
    const sorted = sortOutboxItems([
      item({
        client_mutation_id: "018f0000-0000-7000-8000-000000000041",
        entity_type: "body_measurement",
        entity_id: "018f0000-0000-7000-8000-000000000051",
        op: "upsert",
        client_updated_at: "2026-07-28T16:00:00.000Z",
        payload: {},
      }),
      item({
        client_mutation_id: "018f0000-0000-7000-8000-000000000040",
        entity_type: "legal_acceptance",
        entity_id: "018f0000-0000-7000-8000-000000000050",
        op: "upsert",
        client_updated_at: "2026-07-28T08:00:00.000Z",
        payload: {},
      }),
      item({
        client_mutation_id: "018f0000-0000-7000-8000-000000000042",
        entity_type: "workout_session",
        entity_id: "018f0000-0000-7000-8000-000000000052",
        op: "upsert",
        client_updated_at: "2026-07-28T09:00:00.000Z",
        payload: { local_date: "2026-07-28" },
      }),
    ]);
    expect(sorted.map((i) => i.entity_type)).toEqual([
      "legal_acceptance",
      "workout_session",
      "body_measurement",
    ]);
  });

  it("places regression decisions after satellite create and before sessions", () => {
    const sorted = sortOutboxItems([
      item({
        client_mutation_id: "018f0000-0000-7000-8000-000000000001",
        entity_type: "workout_session",
        entity_id: "018f0000-0000-7000-8000-000000000011",
        op: "upsert",
      }),
      item({
        client_mutation_id: "018f0000-0000-7000-8000-000000000002",
        entity_type: "satellite_regression_decision",
        entity_id: "018f0000-0000-7000-8000-000000000012",
        op: "upsert",
      }),
      item({
        client_mutation_id: "018f0000-0000-7000-8000-000000000003",
        entity_type: "satellite",
        entity_id: "018f0000-0000-7000-8000-000000000013",
        op: "upsert",
      }),
      item({
        client_mutation_id: "018f0000-0000-7000-8000-000000000004",
        entity_type: "legal_acceptance",
        entity_id: "018f0000-0000-7000-8000-000000000014",
        op: "upsert",
      }),
    ]);
    expect(sorted.map((i) => i.entity_type)).toEqual([
      "legal_acceptance",
      "satellite",
      "satellite_regression_decision",
      "workout_session",
    ]);
  });

  it("takeFlushWindow caps at 20 after topo", () => {
    const items = Array.from({ length: 25 }, (_, i) =>
      item({
        client_mutation_id: `018f0000-0000-7000-8000-${String(i).padStart(12, "0")}`,
        entity_type: "body_measurement",
        entity_id: `018f0000-0000-7000-8000-${String(i + 100).padStart(12, "0")}`,
        op: "upsert",
      }),
    );
    expect(takeFlushWindow(items, 20)).toHaveLength(20);
  });

  it("tie-breaks same-type satellites by entity_id then mutation id", () => {
    const sorted = sortOutboxItems([
      item({
        client_mutation_id: "018f0000-0000-7000-8000-0000000000b2",
        entity_type: "satellite",
        entity_id: "018f0000-0000-7000-8000-000000000014",
        op: "upsert",
        client_updated_at: "2026-07-28T10:00:00.000Z",
        payload: { client_updated_at: "2026-07-28T10:00:00.000Z" },
      }),
      item({
        client_mutation_id: "018f0000-0000-7000-8000-0000000000b1",
        entity_type: "satellite",
        entity_id: "018f0000-0000-7000-8000-000000000013",
        op: "upsert",
        client_updated_at: "2026-07-28T10:00:00.000Z",
        payload: {},
      }),
      item({
        client_mutation_id: "018f0000-0000-7000-8000-0000000000b3",
        entity_type: "satellite",
        entity_id: "018f0000-0000-7000-8000-000000000014",
        op: "upsert",
        client_updated_at: "2026-07-28T10:00:00.000Z",
        payload: null,
      }),
    ]);
    expect(sorted.map((i) => i.client_mutation_id)).toEqual([
      "018f0000-0000-7000-8000-0000000000b1",
      "018f0000-0000-7000-8000-0000000000b2",
      "018f0000-0000-7000-8000-0000000000b3",
    ]);
  });

  it("uses performed_at when present on sessions", () => {
    const sorted = sortOutboxItems([
      item({
        client_mutation_id: "018f0000-0000-7000-8000-000000000051",
        entity_type: "workout_session",
        entity_id: "018f0000-0000-7000-8000-000000000061",
        op: "upsert",
        client_updated_at: "2026-07-28T08:00:00.000Z",
        payload: { performed_at: "2026-07-28T12:00:00.000Z", local_date: "2026-07-28" },
      }),
      item({
        client_mutation_id: "018f0000-0000-7000-8000-000000000050",
        entity_type: "workout_session",
        entity_id: "018f0000-0000-7000-8000-000000000060",
        op: "upsert",
        client_updated_at: "2026-07-28T09:00:00.000Z",
        payload: { local_date: "2026-07-28" },
      }),
    ]);
    expect(sorted.map((i) => i.client_mutation_id)).toEqual([
      "018f0000-0000-7000-8000-000000000050",
      "018f0000-0000-7000-8000-000000000051",
    ]);
  });
});

describe("ACK classify FR-072b", () => {
  it("marks applied/idempotent/applied_detached as done", () => {
    expect(classifyAck("applied", null)).toEqual({ kind: "done" });
    expect(classifyAck("idempotent", null)).toEqual({ kind: "done" });
    expect(classifyAck("applied_detached", null)).toEqual({ kind: "done" });
  });

  it("retries unknown non-rejected statuses", () => {
    expect(
      classifyAck("pending" as unknown as Parameters<typeof classifyAck>[0], null),
    ).toEqual({ kind: "retry", errorCode: null });
  });

  it("quarantines revision_jump and legal_required", () => {
    expect(classifyAck("rejected", "revision_jump")).toEqual({
      kind: "quarantine",
      errorCode: "revision_jump",
    });
    expect(classifyAck("rejected", "legal_required")).toEqual({
      kind: "quarantine",
      errorCode: "legal_required",
    });
  });

  it("quarantines dependency error codes", () => {
    expect(classifyAck("rejected", "dependency_missing").kind).toBe("quarantine");
    expect(classifyAck("rejected", "dependency_failed").kind).toBe("quarantine");
    expect(classifyAck("rejected", "dependency_cycle").kind).toBe("quarantine");
  });

  it("routes conflicts to conflict action", () => {
    expect(classifyAck("conflict_lost", null).kind).toBe("conflict");
    expect(classifyAck("conflict_tie", null).kind).toBe("conflict");
    expect(classifyAck("session_immutable_after_evaluate", null).kind).toBe("conflict");
  });

  it("caps backoff at 15 minutes", () => {
    expect(nextBackoffMs(20)).toBeLessThanOrEqual(15 * 60_000 + 500);
    expect(nextBackoffMs(0)).toBeGreaterThanOrEqual(1000);
  });

  it("quarantines unknown rejected codes", () => {
    expect(classifyAck("rejected", "weird_code")).toEqual({
      kind: "quarantine",
      errorCode: "weird_code",
    });
  });
});
