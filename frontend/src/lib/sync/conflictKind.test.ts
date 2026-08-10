import { describe, expect, it } from "vitest";

import {
  conflictIsLost,
  conflictKindI18nKey,
  conflictNeedsModal,
  parseLosingPayload,
} from "@/lib/sync/conflictKind";
import { canRecoverConflict } from "@/lib/sync/recoverConflict";
import type { CachedConflict } from "@/lib/db/types";

describe("conflictKind (FR-073a)", () => {
  it("marks tie and immutable as modal", () => {
    expect(conflictNeedsModal("conflict_tie")).toBe(true);
    expect(conflictNeedsModal("tie_revision")).toBe(true);
    expect(conflictNeedsModal("session_immutable_after_evaluate")).toBe(true);
    expect(conflictNeedsModal("session_date_immutable")).toBe(true);
    expect(conflictNeedsModal("conflict_lost")).toBe(false);
    expect(conflictNeedsModal("lost_push")).toBe(false);
  });

  it("detects lost kinds for toast", () => {
    expect(conflictIsLost("lost_push")).toBe(true);
    expect(conflictIsLost("conflict_lost")).toBe(true);
    expect(conflictIsLost("tie_revision")).toBe(false);
  });

  it("maps i18n keys", () => {
    expect(conflictKindI18nKey("tie_revision")).toBe("sync.conflictKindTie");
    expect(conflictKindI18nKey("lost_push")).toBe("sync.conflictKindLost");
  });

  it("parses losing payload", () => {
    const doc = parseLosingPayload({
      schema_version: 1,
      op: "upsert",
      revision: 2,
      payload: { schema_version: 1, local_date: "2026-08-10" },
    });
    expect(doc?.op).toBe("upsert");
    expect(doc?.payload?.local_date).toBe("2026-08-10");
  });
});

describe("canRecoverConflict", () => {
  const base: CachedConflict = {
    id: "018f0000-0000-7000-8000-000000000099",
    entity_type: "workout_session",
    entity_id: "018f0000-0000-7000-8000-000000000098",
    conflict_kind: "conflict_tie",
    created_at: "2026-08-10T12:00:00.000Z",
    acknowledged: false,
    losing_payload: {
      schema_version: 1,
      op: "upsert",
      revision: 2,
      payload: {
        schema_version: 1,
        local_date: "2026-08-10",
        performed_at: "2026-08-10T10:00:00.000Z",
        logs: [],
      },
    },
  };

  it("allows session and measurement upsert recovery", () => {
    expect(canRecoverConflict(base)).toBe(true);
    expect(
      canRecoverConflict({
        ...base,
        entity_type: "body_measurement",
        losing_payload: {
          schema_version: 1,
          op: "upsert",
          payload: { schema_version: 1, metrics: { schema_version: 1 } },
        },
      }),
    ).toBe(true);
  });

  it("rejects delete and unsupported entities", () => {
    expect(
      canRecoverConflict({
        ...base,
        losing_payload: { schema_version: 1, op: "delete", payload: {} },
      }),
    ).toBe(false);
    expect(canRecoverConflict({ ...base, entity_type: "satellite" })).toBe(false);
    expect(canRecoverConflict({ ...base, losing_payload: null })).toBe(false);
  });
});
