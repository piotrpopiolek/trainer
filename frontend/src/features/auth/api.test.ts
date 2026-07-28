import { afterEach, describe, expect, it, vi } from "vitest";

import {
  acceptDisclaimer,
  completeOnboarding,
  fetchDisclaimer,
  fetchMe,
  logout,
  logoutAll,
} from "@/features/auth/api";

describe("auth api", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetchMe parses profile", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            schema_version: 1,
            id: "018f0000-0000-7000-8000-000000000001",
            email: "a@b.c",
            display_name: "A",
            locale: "pl-PL",
            timezone: "Europe/Warsaw",
            onboarding_completed: true,
            health_disclaimer_accepted: true,
            csrf_token: "t",
          }),
          { status: 200 },
        ),
      ),
    );
    const me = await fetchMe();
    expect(me.email).toBe("a@b.c");
  });

  it("fetchDisclaimer and acceptDisclaimer call endpoints", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            schema_version: 1,
            document_id: "018f0000-0000-7000-8000-000000000002",
            slug: "health_disclaimer",
            version: "1",
            locale: "pl-PL",
            title: "T",
            body: "B",
            content_hash: "a".repeat(64),
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            schema_version: 1,
            accepted: true,
            document_id: "018f0000-0000-7000-8000-000000000002",
          }),
          { status: 200 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const doc = await fetchDisclaimer();
    await acceptDisclaimer(doc);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("completeOnboarding and logout post", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            schema_version: 1,
            completed: true,
            recommended_steps: {},
            chosen_steps: {},
          }),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await completeOnboarding({
      experience_level: "beginner",
      training_days_per_week: 3,
      goals: ["strength"],
      anchor_weekday: 1,
      timezone: "Europe/Warsaw",
    });
    await logout();
    await logoutAll();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
