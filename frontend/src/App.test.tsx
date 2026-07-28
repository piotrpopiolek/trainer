import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { App } from "@/App";
import "@/lib/i18n";

function renderAt(path: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("App routes", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows login brand and Google CTA", async () => {
    renderAt("/login");
    expect(screen.getByRole("heading", { name: "Zaloguj się" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zaloguj przez Google" })).toBeInTheDocument();
  });

  it("redirects unauthenticated users from / to /login", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error_code: "unauthorized" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    renderAt("/");
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Zaloguj się" })).toBeInTheDocument();
    });
  });
});
