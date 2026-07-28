import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { ProgressionEvent } from "@/lib/schemas";

type SeenEventsState = {
  seenIds: string[];
  markSeen: (id: string) => void;
  filterUnseen: (events: ProgressionEvent[]) => ProgressionEvent[];
};

/** FR-036: surface advance/regress once per event.id */
export const useSeenEventsStore = create<SeenEventsState>()(
  persist(
    (set, get) => ({
      seenIds: [],
      markSeen: (id) => {
        const cur = get().seenIds;
        if (cur.includes(id)) return;
        set({ seenIds: [...cur, id].slice(-200) });
      },
      filterUnseen: (events) => {
        const seen = new Set(get().seenIds);
        return events.filter(
          (e) =>
            (e.event_type === "advance" || e.event_type === "regress") &&
            !seen.has(e.id),
        );
      },
    }),
    { name: "trainer.seen-progression-events" },
  ),
);
