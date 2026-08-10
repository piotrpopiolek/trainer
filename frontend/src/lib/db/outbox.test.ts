import "fake-indexeddb/auto";

import { afterEach, describe, expect, it } from "vitest";

import { clearUserDb } from "@/lib/db/open";
import {
  enqueueOutbox,
  listFlushableOutbox,
  outboxCounts,
  requeueQuarantineItem,
  updateOutboxItem,
} from "@/lib/db/outbox";
import { getOrCreateDeviceId, setPersistedFlag, getPersistedFlag } from "@/lib/db/meta";

const USER = "018f0000-0000-7000-8000-00000000db01";

afterEach(async () => {
  await clearUserDb(USER);
});

describe("indexeddb outbox", () => {
  it("enqueues and counts pending items", async () => {
    await enqueueOutbox(USER, {
      entity_type: "workout_session",
      entity_id: "018f0000-0000-7000-8000-0000000000a1",
      payload: {
        schema_version: 1,
        performed_at: "2026-07-28T10:00:00.000Z",
        local_date: "2026-07-28",
      },
    });
    const counts = await outboxCounts(USER);
    expect(counts.pending).toBe(1);
    const flushable = await listFlushableOutbox(USER);
    expect(flushable).toHaveLength(1);
  });

  it("requeues quarantine item to pending (FR-072b)", async () => {
    const item = await enqueueOutbox(USER, {
      entity_type: "workout_session",
      entity_id: "018f0000-0000-7000-8000-0000000000a2",
      payload: { schema_version: 1, local_date: "2026-08-10" },
    });
    await updateOutboxItem(USER, {
      ...item,
      status: "quarantine",
      last_error_code: "revision_jump",
    });
    expect((await outboxCounts(USER)).quarantine).toBe(1);
    const next = await requeueQuarantineItem(USER, item.client_mutation_id);
    expect(next?.status).toBe("pending");
    expect(next?.last_error_code).toBeNull();
    const counts = await outboxCounts(USER);
    expect(counts.quarantine).toBe(0);
    expect(counts.pending).toBe(1);
  });

  it("persists device id and storage flag", async () => {
    const a = await getOrCreateDeviceId(USER);
    const b = await getOrCreateDeviceId(USER);
    expect(a).toBe(b);
    await setPersistedFlag(USER, true);
    expect(await getPersistedFlag(USER)).toBe(true);
  });
});
