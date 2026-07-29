import "fake-indexeddb/auto";

import { afterEach, describe, expect, it } from "vitest";

import { clearUserDb } from "@/lib/db/open";
import { enqueueOutbox, listFlushableOutbox, outboxCounts } from "@/lib/db/outbox";
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

  it("persists device id and storage flag", async () => {
    const a = await getOrCreateDeviceId(USER);
    const b = await getOrCreateDeviceId(USER);
    expect(a).toBe(b);
    await setPersistedFlag(USER, true);
    expect(await getPersistedFlag(USER)).toBe(true);
  });
});
