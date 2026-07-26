import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, afterEach } from "vitest";

import { App } from "@/App";
import "@/lib/i18n";

function renderApp() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

describe("App shell", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders brand via i18n and healthy API status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    renderApp();

    expect(screen.getByRole("heading", { name: "Trainer" })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("API działa")).toBeInTheDocument();
    });
  });

  it("shows API down copy when health fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 503 })));

    renderApp();

    await waitFor(() => {
      expect(screen.getByText("API niedostępne")).toBeInTheDocument();
    });
  });
});
