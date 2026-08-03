import { describe, expect, it } from "vitest";

import { todaySatelliteSchema, type ProgressionEvent } from "@/lib/schemas";
import { useSeenEventsStore } from "@/stores/seenEventsStore";

function ev(
  partial: Partial<ProgressionEvent> & Pick<ProgressionEvent, "id" | "event_type">,
): ProgressionEvent {
  return {
    schema_version: 1,
    exercise_id: "018f0000-0000-7000-8000-000000000001",
    from_step: 1,
    to_step: 2,
    created_at: "2026-08-03T12:00:00Z",
    ...partial,
  };
}

describe("seenEventsStore Slice F", () => {
  it("surfaces satellite_advance and satellite_regress_confirmed", () => {
    useSeenEventsStore.setState({ seenIds: [] });
    const unseen = useSeenEventsStore.getState().filterUnseen([
      ev({ id: "018f0000-0000-7000-8000-0000000000a1", event_type: "satellite_advance" }),
      ev({
        id: "018f0000-0000-7000-8000-0000000000a2",
        event_type: "satellite_regress_confirmed",
      }),
      ev({
        id: "018f0000-0000-7000-8000-0000000000a3",
        event_type: "satellite_regress_suggested",
      }),
      ev({ id: "018f0000-0000-7000-8000-0000000000a4", event_type: "advance" }),
    ]);
    expect(unseen.map((e) => e.event_type)).toEqual([
      "satellite_advance",
      "satellite_regress_confirmed",
      "advance",
    ]);
  });
});

describe("todaySatelliteSchema Slice F", () => {
  it("parses pending_regression from API", () => {
    const parsed = todaySatelliteSchema.parse({
      schema_version: 1,
      exercise_id: "018f0000-0000-7000-8000-000000000010",
      name: "Copenhagen Plank",
      exercise_type: "B",
      current_step_number: 2,
      step_name: "Long lever hold",
      pending_regression: {
        schema_version: 1,
        id: "018f0000-0000-7000-8000-000000000011",
        from_step: 2,
        to_step: 1,
        status: "pending",
      },
    });
    expect(parsed.pending_regression?.from_step).toBe(2);
    expect(parsed.pending_regression?.to_step).toBe(1);
  });
});
