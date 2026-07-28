import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch, apiJson, googleStartUrl } from "@/lib/api";

describe("apiFetch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls relative /api paths with credentials include", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/api/health");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/health",
      expect.objectContaining({ credentials: "include" }),
    );
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get("Accept")).toBe("application/json");
  });

  it("prefixes non-absolute paths with /api/", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("health");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/health",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("preserves an existing Accept header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/api/health", { headers: { Accept: "text/plain" } });

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get("Accept")).toBe("text/plain");
  });
});

describe("apiJson", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("parses JSON success bodies", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    await expect(apiJson<{ ok: boolean }>("/api/x")).resolves.toEqual({ ok: true });
  });

  it("throws ApiError with error_code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error_code: "legal_required" }), {
          status: 422,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    await expect(apiJson("/api/x")).rejects.toMatchObject({
      name: "ApiError",
      status: 422,
      errorCode: "legal_required",
    } satisfies Partial<ApiError>);
  });

  it("handles 204 and non-JSON error bodies", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response("nope", { status: 500 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(apiJson("/api/empty")).resolves.toBeUndefined();
    await expect(apiJson("/api/bad")).rejects.toMatchObject({ errorCode: "http_500" });
  });

  it("attaches CSRF header when provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await apiJson("/api/account/export", {
      method: "POST",
      csrfToken: "tok",
      body: "{}",
    });
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("tok");
  });
});

describe("googleStartUrl", () => {
  it("returns OAuth start path", () => {
    expect(googleStartUrl()).toBe("/api/auth/google/start");
  });
});
