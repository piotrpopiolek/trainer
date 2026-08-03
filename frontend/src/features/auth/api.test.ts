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
    const result = await acceptDisclaimer(doc);
    expect(result.pendingSync).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("acceptDisclaimer enqueues when offline", async () => {
    const { useAuthStore } = await import("@/stores/authStore");
    useAuthStore.getState().setMe({
      schema_version: 1,
      id: "018f0000-0000-7000-8000-000000000001",
      email: "a@b.c",
      display_name: "A",
      locale: "pl-PL",
      timezone: "Europe/Warsaw",
      onboarding_completed: true,
      health_disclaimer_accepted: false,
      csrf_token: "t",
    });
    vi.stubGlobal("navigator", {
      ...navigator,
      onLine: false,
      storage: { persist: async () => false },
    });
    const doc = {
      schema_version: 1 as const,
      document_id: "018f0000-0000-7000-8000-000000000002",
      slug: "health_disclaimer",
      version: "1",
      locale: "pl-PL",
      title: "T",
      body: "B",
      content_hash: "a".repeat(64),
    };
    const result = await acceptDisclaimer(doc);
    expect(result.pendingSync).toBe(true);
  });

  it("acceptDisclaimer falls back to outbox on network TypeError", async () => {
    const { useAuthStore } = await import("@/stores/authStore");
    useAuthStore.getState().setMe({
      schema_version: 1,
      id: "018f0000-0000-7000-8000-000000000001",
      email: "a@b.c",
      display_name: "A",
      locale: "pl-PL",
      timezone: "Europe/Warsaw",
      onboarding_completed: true,
      health_disclaimer_accepted: false,
      csrf_token: "t",
    });
    vi.stubGlobal("navigator", {
      ...navigator,
      onLine: true,
      storage: { persist: async () => false },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    const doc = {
      schema_version: 1 as const,
      document_id: "018f0000-0000-7000-8000-000000000002",
      slug: "health_disclaimer",
      version: "1",
      locale: "pl-PL",
      title: "T",
      body: "B",
      content_hash: "a".repeat(64),
    };
    const result = await acceptDisclaimer(doc);
    expect(result.pendingSync).toBe(true);
  });

  it("acceptDisclaimer rethrows client ApiError without outbox fallback", async () => {
    const { useAuthStore } = await import("@/stores/authStore");
    useAuthStore.getState().setMe({
      schema_version: 1,
      id: "018f0000-0000-7000-8000-000000000001",
      email: "a@b.c",
      display_name: "A",
      locale: "pl-PL",
      timezone: "Europe/Warsaw",
      onboarding_completed: true,
      health_disclaimer_accepted: false,
      csrf_token: "t",
    });
    vi.stubGlobal("navigator", {
      ...navigator,
      onLine: true,
      storage: { persist: async () => false },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error_code: "schema_invalid" }), {
          status: 422,
        }),
      ),
    );
    const doc = {
      schema_version: 1 as const,
      document_id: "018f0000-0000-7000-8000-000000000002",
      slug: "health_disclaimer",
      version: "1",
      locale: "pl-PL",
      title: "T",
      body: "B",
      content_hash: "a".repeat(64),
    };
    await expect(acceptDisclaimer(doc)).rejects.toMatchObject({
      status: 422,
      errorCode: "schema_invalid",
    });
  });

  it("patchSchedule sends CSRF", async () => {
    const { useAuthStore } = await import("@/stores/authStore");
    useAuthStore.getState().setMe({
      schema_version: 1,
      id: "018f0000-0000-7000-8000-000000000001",
      email: "a@b.c",
      display_name: "A",
      locale: "pl-PL",
      timezone: "Europe/Warsaw",
      onboarding_completed: true,
      health_disclaimer_accepted: true,
      csrf_token: "csrf-token",
    });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          schema_version: 1,
          pending_timezone: "UTC",
          timezone_effective_on: "2026-07-29",
          pending_anchor_weekday: 2,
          schedule_effective_on: "2026-07-29",
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { patchSchedule } = await import("@/features/auth/api");
    await patchSchedule({ pending_timezone: "UTC", pending_anchor_weekday: 2 });
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("X-CSRF-Token")).toBe("csrf-token");
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
