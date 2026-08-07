import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  cloneSatellite,
  createMeasurement,
  createSatellite,
  createSession,
  decideSatelliteRegression,
  fetchCatalogCc,
  fetchToday,
  listMeasurements,
  listProgress,
  listSatellites,
  overrideProgress,
  softDeleteSession,
  updateSatellite,
} from "@/features/training/api";
import { useAuthStore } from "@/stores/authStore";

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

const satFixture = {
  schema_version: 1,
  id: "018f0000-0000-7000-8000-000000000020",
  name: "Band",
  exercise_type: "B",
  active_metrics: { schema_version: 1, metrics: ["reps"] },
  schedule_kind: "daily",
  revision: 2,
  current_config_version_id: "018f0000-0000-7000-8000-000000000022",
  progression: { mode: "goal_only" as const },
  steps: [{ step_number: 1, name: "Cel", rules: { schema_version: 1 } }],
};

describe("training api", () => {
  beforeEach(() => {
    useAuthStore.getState().clear();
  });

  afterEach(() => {
    useAuthStore.getState().clear();
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
      schema_version: 1,
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
      schema_version: 1,
      id: "018f0000-0000-7000-8000-000000000020",
      name: "Band",
      exercise_type: "B",
      active_metrics: { schema_version: 1 },
      schedule_kind: "daily",
      revision: 1,
      steps: [{}],
    };
    const meas = {
      schema_version: 1,
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
      .mockResolvedValueOnce(new Response(JSON.stringify(sat), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(sat), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [meas] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(meas), { status: 200 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            progress: {
              schema_version: 1,
              exercise_id: "018f0000-0000-7000-8000-000000000011",
              current_step_number: 2,
              fail_streak: 0,
              is_active: true,
            },
            event: {
              schema_version: 1,
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
      stepName: "Cel",
    });
    await createSatellite({
      name: "Hip Thrust",
      exercise_type: "B",
      schedule_kind: "daily",
      goalSets: 3,
      goalReps: 10,
      requireBothSides: true,
      trackWeight: true,
      stepName: "Cel",
    });
    await createSatellite({
      name: "Mobility",
      exercise_type: "C",
      schedule_kind: "daily",
      stepName: "Cel",
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

  it("updateSatellite covers step and progression write branches", async () => {
    useAuthStore.getState().setMe({
      schema_version: 1,
      id: "018f0000-0000-7000-8000-000000000001",
      email: "a@b.c",
      display_name: null,
      locale: "pl-PL",
      timezone: "Europe/Warsaw",
      onboarding_completed: true,
      health_disclaimer_accepted: true,
      csrf_token: "csrf-sat",
    });
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify(satFixture), { status: 200 })),
    );
    vi.stubGlobal("fetch", fetchMock);

    const base = {
      id: satFixture.id,
      revision: 1,
      name: "Band",
      exercise_type: "B" as const,
      schedule_kind: "daily" as const,
      active_metrics: { schema_version: 1, metrics: ["reps"] },
    };

    await updateSatellite({
      ...base,
      progression: { mode: "goal_only" },
      steps: [
        {
          sort_order: 2,
          step_id: "018f0000-0000-7000-8000-000000000031",
          name: "A",
          description: "desc",
          rules: { schema_version: 1 },
        },
      ],
    });
    await updateSatellite({
      ...base,
      progression: {
        mode: "steps",
        regression: { mode: "suggest_after_failed_days", threshold: 3 },
      },
      steps: [
        { step_number: 1, rules: { schema_version: 1 } },
        { step_number: 2, rules: { schema_version: 1 } },
      ],
    });
    await updateSatellite({
      ...base,
      progression: { mode: "steps" } as { mode: "steps"; regression: unknown },
      steps: [
        { step_number: 1, rules: { schema_version: 1 } },
        { step_number: 2, rules: { schema_version: 1 } },
      ],
    });
    await updateSatellite({
      ...base,
      steps: [{ step_number: "bad", rules: { schema_version: 1 } }],
    });
    await updateSatellite({
      ...base,
      steps: [
        { step_number: 1, rules: { schema_version: 1 } },
        { step_number: 2, rules: { schema_version: 1 } },
      ],
    });

    expect(fetchMock).toHaveBeenCalledTimes(5);
    const bodies = fetchMock.mock.calls.map((c) => JSON.parse(String(c[1]?.body)));
    expect(bodies[0].progression).toEqual({ mode: "goal_only" });
    expect(bodies[0].steps[0]).toMatchObject({
      step_number: 2,
      step_id: "018f0000-0000-7000-8000-000000000031",
      name: "A",
      description: "desc",
    });
    expect(bodies[1].progression).toEqual({
      mode: "steps",
      regression: { mode: "suggest_after_failed_days", threshold: 3 },
    });
    expect(bodies[2].progression).toEqual({
      mode: "steps",
      regression: { mode: "suggest_after_failed_days", threshold: 2 },
    });
    expect(bodies[3].progression).toEqual({ mode: "goal_only" });
    expect(bodies[3].steps[0].step_number).toBe(1);
    expect(bodies[4].progression).toEqual({
      mode: "steps",
      regression: { mode: "suggest_after_failed_days", threshold: 2 },
    });
    const headers = fetchMock.mock.calls[0][1]?.headers as Headers;
    expect(headers.get("X-CSRF-Token")).toBe("csrf-sat");
  });

  it("cloneSatellite and decideSatelliteRegression", async () => {
    useAuthStore.getState().setMe({
      schema_version: 1,
      id: "018f0000-0000-7000-8000-000000000001",
      email: "a@b.c",
      display_name: null,
      locale: "pl-PL",
      timezone: "Europe/Warsaw",
      onboarding_completed: true,
      health_disclaimer_accepted: true,
      csrf_token: "csrf-dec",
    });
    const progress = {
      schema_version: 1,
      exercise_id: satFixture.id,
      current_step_number: 1,
      fail_streak: 0,
      is_active: true,
    };
    const event = {
      schema_version: 1,
      id: "018f0000-0000-7000-8000-000000000040",
      exercise_id: satFixture.id,
      event_type: "regress",
      from_step: 2,
      to_step: 1,
      created_at: "2026-07-28T10:00:00Z",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            ...satFixture,
            id: "018f0000-0000-7000-8000-000000000021",
            name: "Band (kopia)",
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            recommendation_id: "018f0000-0000-7000-8000-000000000041",
            status: "accepted",
            progress,
            event,
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            recommendation_id: "018f0000-0000-7000-8000-000000000042",
            status: "declined",
            progress,
            event: null,
          }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    const cloned = await cloneSatellite(satFixture.id, { name: "Band (kopia)" });
    expect(cloned.name).toBe("Band (kopia)");

    const accepted = await decideSatelliteRegression(
      satFixture.id,
      "018f0000-0000-7000-8000-000000000041",
      "accept",
    );
    expect(accepted.status).toBe("accepted");
    expect(accepted.event?.event_type).toBe("regress");

    const declined = await decideSatelliteRegression(
      satFixture.id,
      "018f0000-0000-7000-8000-000000000042",
      "decline",
    );
    expect(declined.event).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("listProgress and fetchCatalogCc", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({
              items: [
                {
                  schema_version: 1,
                  exercise_id: "018f0000-0000-7000-8000-000000000011",
                  current_step_number: 3,
                  fail_streak: 0,
                  is_active: true,
                },
              ],
            }),
            { status: 200 },
          ),
        )
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({
              schema_version: 1,
              exercises: [
                {
                  schema_version: 1,
                  id: "018f0000-0000-7000-8000-000000000011",
                  name: "Pompki",
                  slug: "push_ups",
                  description: null,
                  exercise_type: "A",
                  steps: [
                    {
                      schema_version: 1,
                      step_number: 1,
                      name: "Pion",
                      description: "Opis",
                      execution: "",
                      rationale: "",
                      technique: "",
                      content_status: "ready",
                      rules: { schema_version: 2 },
                    },
                  ],
                },
              ],
            }),
            { status: 200 },
          ),
        ),
    );
    expect(await listProgress()).toHaveLength(1);
    const cat = await fetchCatalogCc();
    expect(cat.exercises[0]?.name).toBe("Pompki");
    expect(cat.exercises[0]?.steps).toHaveLength(1);
  });
});
