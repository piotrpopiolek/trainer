import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { ProgressionEvent } from "@/lib/schemas";

type SeenEventsState = {
  seenIds: string[];
  markSeen: (id: string) => void;
  filterUnseen: (events: ProgressionEvent[]) => ProgressionEvent[];
};

/** FR-036 / FR-053: surface CC + satellite progression events once per event.id */
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
        const surface = new Set([
          "advance",
          "regress",
          "satellite_advance",
          "satellite_regress_confirmed",
        ]);
        return events.filter((e) => surface.has(e.event_type) && !seen.has(e.id));
      },
    }),
    { name: "trainer.seen-progression-events" },
  ),
);
