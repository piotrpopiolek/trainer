import { beforeEach, describe, expect, it } from "vitest";

import type { ProgressionEvent } from "@/lib/schemas";
import { useAuthStore } from "@/stores/authStore";
import { useSeenEventsStore } from "@/stores/seenEventsStore";

describe("authStore", () => {
  beforeEach(() => {
    useAuthStore.getState().clear();
  });

  it("stores me and csrf", () => {
    useAuthStore.getState().setMe({
      schema_version: 1,
      id: "018f0000-0000-7000-8000-000000000001",
      email: "a@b.c",
      display_name: null,
      locale: "pl-PL",
      timezone: "Europe/Warsaw",
      onboarding_completed: false,
      health_disclaimer_accepted: false,
      csrf_token: "csrf",
    });
    expect(useAuthStore.getState().csrfToken).toBe("csrf");
    useAuthStore.getState().setCsrfToken("other");
    expect(useAuthStore.getState().csrfToken).toBe("other");
    useAuthStore.getState().setMe(null);
    expect(useAuthStore.getState().csrfToken).toBeNull();
    useAuthStore.getState().clear();
    expect(useAuthStore.getState().me).toBeNull();
  });
});

describe("seenEventsStore", () => {
  beforeEach(() => {
    useSeenEventsStore.setState({ seenIds: [] });
  });

  it("filters advance/regress and marks seen", () => {
    const events: ProgressionEvent[] = [
      {
        id: "018f0000-0000-7000-8000-0000000000aa",
        exercise_id: "018f0000-0000-7000-8000-0000000000bb",
        event_type: "advance",
        from_step: 1,
        to_step: 2,
        created_at: "2026-07-28T10:00:00Z",
      },
      {
        id: "018f0000-0000-7000-8000-0000000000cc",
        exercise_id: "018f0000-0000-7000-8000-0000000000bb",
        event_type: "note",
        from_step: 1,
        to_step: 1,
        created_at: "2026-07-28T10:00:00Z",
      },
    ];
    const unseen = useSeenEventsStore.getState().filterUnseen(events);
    expect(unseen).toHaveLength(1);
    useSeenEventsStore.getState().markSeen(events[0]!.id);
    useSeenEventsStore.getState().markSeen(events[0]!.id); // idempotent
    expect(useSeenEventsStore.getState().filterUnseen(events)).toHaveLength(0);
  });
});
