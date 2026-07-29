import { create } from "zustand";

import { listConflicts } from "@/lib/db/cache";
import { outboxCounts } from "@/lib/db/outbox";
import { readPersisted } from "@/lib/db/persist";
import type { CachedConflict } from "@/lib/db/types";
import type { ProgressionEvent } from "@/lib/schemas";

type SyncState = {
  userId: string | null;
  online: boolean;
  persisted: boolean | null;
  pending: number;
  inFlight: number;
  quarantine: number;
  oldestPendingAt: string | null;
  conflicts: CachedConflict[];
  transportFailStreak: number;
  lastFlushError: string | null;
  recentEvents: ProgressionEvent[];
  lastConflictToast: CachedConflict | null;
  setOnline: (online: boolean) => void;
  setUserId: (userId: string | null) => void;
  refresh: () => Promise<void>;
  bumpTransportFail: () => void;
  resetTransportFail: () => void;
  pushEvents: (events: ProgressionEvent[]) => void;
  clearEvents: () => void;
  setLastConflictToast: (c: CachedConflict | null) => void;
  reset: () => void;
};

export const useSyncStore = create<SyncState>((set, get) => ({
  userId: null,
  online: typeof navigator === "undefined" ? true : navigator.onLine,
  persisted: null,
  pending: 0,
  inFlight: 0,
  quarantine: 0,
  oldestPendingAt: null,
  conflicts: [],
  transportFailStreak: 0,
  lastFlushError: null,
  recentEvents: [],
  lastConflictToast: null,
  setOnline: (online) => set({ online }),
  setUserId: (userId) => set({ userId }),
  refresh: async () => {
    const userId = get().userId;
    if (!userId) return;
    const counts = await outboxCounts(userId);
    const conflicts = await listConflicts(userId);
    const persisted = await readPersisted(userId);
    set({
      pending: counts.pending,
      inFlight: counts.in_flight,
      quarantine: counts.quarantine,
      oldestPendingAt: counts.oldestPendingAt,
      conflicts,
      persisted,
    });
  },
  bumpTransportFail: () =>
    set((s) => ({ transportFailStreak: s.transportFailStreak + 1 })),
  resetTransportFail: () => set({ transportFailStreak: 0, lastFlushError: null }),
  pushEvents: (events) =>
    set((s) => ({ recentEvents: [...s.recentEvents, ...events] })),
  clearEvents: () => set({ recentEvents: [] }),
  setLastConflictToast: (c) => set({ lastConflictToast: c }),
  reset: () =>
    set({
      userId: null,
      pending: 0,
      inFlight: 0,
      quarantine: 0,
      oldestPendingAt: null,
      conflicts: [],
      transportFailStreak: 0,
      lastFlushError: null,
      recentEvents: [],
      lastConflictToast: null,
      persisted: null,
    }),
}));

export function pendingOutboxTotal(s: SyncState): number {
  return s.pending + s.inFlight + s.quarantine;
}
