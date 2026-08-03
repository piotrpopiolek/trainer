import { describe, expect, it } from "vitest";

import { canonicalize, sha256JcsHex } from "@/lib/canonicalJson";
import { buildOfflineSatellitePin } from "@/lib/satelliteOfflinePin";
import { resolveSessionDependsOn } from "@/lib/sync/dependsOn";
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

describe("resolveSessionDependsOn Slice D", () => {
  it("links pending legal and matching satellite create", () => {
    const legal = "018f0000-0000-7000-8000-0000000000a1";
    const satMut = "018f0000-0000-7000-8000-0000000000a2";
    const satEx = "018f0000-0000-7000-8000-0000000000b1";
    const otherSat = "018f0000-0000-7000-8000-0000000000b2";
    const deps = resolveSessionDependsOn({
      pending: [
        item({
          client_mutation_id: legal,
          entity_type: "legal_acceptance",
          entity_id: "018f0000-0000-7000-8000-0000000000c1",
          op: "upsert",
        }),
        item({
          client_mutation_id: satMut,
          entity_type: "satellite",
          entity_id: satEx,
          op: "upsert",
        }),
        item({
          client_mutation_id: "018f0000-0000-7000-8000-0000000000a3",
          entity_type: "satellite",
          entity_id: otherSat,
          op: "upsert",
        }),
      ],
      localDate: "2026-08-03",
      logs: [{ exercise_id: satEx, exercise_kind: "satellite" }],
    });
    expect(deps).toEqual([legal, satMut].sort());
  });

  it("links tombstone delete for same local_date", () => {
    const tomb = "018f0000-0000-7000-8000-0000000000d1";
    const deps = resolveSessionDependsOn({
      pending: [
        item({
          client_mutation_id: tomb,
          entity_type: "workout_session",
          entity_id: "018f0000-0000-7000-8000-0000000000e1",
          op: "delete",
          payload: { local_date: "2026-08-03" },
        }),
        item({
          client_mutation_id: "018f0000-0000-7000-8000-0000000000d2",
          entity_type: "workout_session",
          entity_id: "018f0000-0000-7000-8000-0000000000e2",
          op: "delete",
          payload: { local_date: "2026-08-02" },
        }),
      ],
      localDate: "2026-08-03",
      logs: [
        {
          exercise_id: "018f0000-0000-7000-8000-0000000000f1",
          exercise_kind: "cc",
        },
      ],
    });
    expect(deps).toEqual([tomb]);
  });

  it("merges explicit extraDependsOn", () => {
    const extra = "018f0000-0000-7000-8000-0000000000aa";
    expect(
      resolveSessionDependsOn({
        pending: [],
        localDate: "2026-08-03",
        logs: [],
        extraDependsOn: [extra],
      }),
    ).toEqual([extra]);
  });
});

describe("buildOfflineSatellitePin Slice D", () => {
  it("matches shared golden vector for Hip Thrust-like config", async () => {
    const stepId = "01900000-0000-7000-8000-000000000001";
    const pin = await buildOfflineSatellitePin({
      exercise_type: "B",
      stepName: "Hip Thrust",
      goalSets: 3,
      goalReps: 10,
      requireBothSides: true,
      trackWeight: true,
      configVersionId: "01900000-0000-7000-8000-000000000099",
      stepId,
    });
    expect(canonicalize(pin.document)).toBe(
      '{"active_metrics":{"metrics":["reps","sides","weight_kg"],"schema_version":1},"exercise_type":"B","progression":{"mode":"goal_only"},"schema_version":1,"steps":[{"rules":{"goal":{"min_reps":10,"min_weight_kg":null,"require_both_sides":true,"sets":3,"type":"reps"},"schema_version":1},"sort_order":1,"step_id":"01900000-0000-7000-8000-000000000001"}]}',
    );
    expect(pin.configHash).toBe(
      "70ba1a2d1e5654c6c313acb00a69a39e7dd557ce5041172cb21df8ea23e5e130",
    );
    expect(await sha256JcsHex(pin.document)).toBe(pin.configHash);
  });

  it("pins type C completed goal", async () => {
    const pin = await buildOfflineSatellitePin({
      exercise_type: "C",
      stepName: "Mobility",
      stepId: "01900000-0000-7000-8000-000000000002",
      configVersionId: "01900000-0000-7000-8000-000000000098",
    });
    expect(pin.configHash).toBe(
      "259d3867d2da017da7c5750b0fb4045178cabf3159fa4b32407cf3478e567e13",
    );
  });
});
