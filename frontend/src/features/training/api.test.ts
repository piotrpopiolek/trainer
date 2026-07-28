import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createMeasurement,
  createSatellite,
  createSession,
  fetchToday,
  listMeasurements,
  listSatellites,
  overrideProgress,
  softDeleteSession,
} from "@/features/training/api";

const emptyToday = {
  schema_version: 1,
  local_date: "2026-07-28",
  timezone: "Europe/Warsaw",
  split_day: 1,
  is_rest_day: false,
  requested_locale: "pl-PL",
  resolved_locale: "pl-PL",
  cc_exercises: [],
  satellites: [],
  sessions: [],
  progress: [],
};

describe("training api", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetchToday", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(new Response(JSON.stringify(emptyToday), { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify(emptyToday), { status: 200 })),
    );
    const t = await fetchToday({ localDate: "2026-07-28", ccDayOverride: 2 });
    expect(t.local_date).toBe("2026-07-28");
    const t2 = await fetchToday();
    expect(t2.split_day).toBe(1);
  });

  it("createSession and softDeleteSession", async () => {
    const session = {
      id: "018f0000-0000-7000-8000-000000000010",
      performed_at: "2026-07-28T10:00:00Z",
      local_date: "2026-07-28",
      revision: 1,
      logs: [],
      progression_events: [],
      progress: [],
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(session), { status: 200 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ...session, deleted_at: "2026-07-28T11:00:00Z" }), {
          status: 200,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    await createSession({
      performedAt: session.performed_at,
      localDate: session.local_date,
      clientTimezone: "Europe/Warsaw",
      logs: [
        {
          exercise_id: "018f0000-0000-7000-8000-000000000011",
          exercise_kind: "cc",
          sets: { schema_version: 1, sets: [{ reps: 10 }] },
        },
      ],
    });
    await softDeleteSession(session.id);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("satellites and measurements and override", async () => {
    const sat = {
      id: "018f0000-0000-7000-8000-000000000020",
      name: "Band",
      exercise_type: "B",
      active_metrics: { schema_version: 1 },
      schedule_kind: "daily",
      revision: 1,
      steps: [{}],
    };
    const meas = {
      id: "018f0000-0000-7000-8000-000000000021",
      measured_at: "2026-07-28T10:00:00Z",
      local_date: "2026-07-28",
      metrics: { schema_version: 1, weight_kg: 80 },
      revision: 1,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [sat] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(sat), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [meas] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(meas), { status: 200 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            progress: {
              exercise_id: "018f0000-0000-7000-8000-000000000011",
              current_step_number: 2,
              fail_streak: 0,
              is_active: true,
            },
            event: {
              id: "018f0000-0000-7000-8000-000000000030",
              exercise_id: "018f0000-0000-7000-8000-000000000011",
              event_type: "manual_override",
              from_step: 1,
              to_step: 2,
              created_at: "2026-07-28T10:00:00Z",
            },
          }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    expect(await listSatellites()).toHaveLength(1);
    await createSatellite({
      name: "Band",
      exercise_type: "B",
      schedule_kind: "daily",
      goalSets: 3,
      goalReps: 10,
    });
    expect(await listMeasurements()).toHaveLength(1);
    await createMeasurement({
      measuredAt: meas.measured_at,
      localDate: meas.local_date,
      weightKg: 80,
    });
    const o = await overrideProgress("018f0000-0000-7000-8000-000000000011", 2);
    expect(o.progress.current_step_number).toBe(2);
  });
});
