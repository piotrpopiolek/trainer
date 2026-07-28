import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { LoginPage } from "@/features/auth/pages";
import { ProgressionSurface } from "@/features/progress/ProgressionSurface";
import "@/lib/i18n";
import { useSeenEventsStore } from "@/stores/seenEventsStore";

describe("LoginPage", () => {
  it("renders Google CTA", () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );
    expect(screen.getByRole("button", { name: "Zaloguj przez Google" })).toBeInTheDocument();
  });

  it("shows oauth error from query", () => {
    render(
      <MemoryRouter initialEntries={["/login?error=email_not_verified"]}>
        <LoginPage />
      </MemoryRouter>,
    );
    expect(
      screen.getByText("Zweryfikuj e-mail w Google i spróbuj ponownie."),
    ).toBeInTheDocument();
  });
});

describe("ProgressionSurface", () => {
  beforeEach(() => {
    useSeenEventsStore.setState({ seenIds: [] });
  });

  it("acks advance modal", async () => {
    const user = userEvent.setup();
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <ProgressionSurface
          events={[
            {
              id: "018f0000-0000-7000-8000-0000000000aa",
              exercise_id: "018f0000-0000-7000-8000-0000000000bb",
              event_type: "advance",
              from_step: 1,
              to_step: 2,
              created_at: "2026-07-28T10:00:00Z",
            },
          ]}
          names={{ "018f0000-0000-7000-8000-0000000000bb": "Pompki" }}
        />
      </QueryClientProvider>,
    );
    expect(screen.getByRole("heading", { name: "Awans!" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "OK" }));
    expect(useSeenEventsStore.getState().seenIds).toContain(
      "018f0000-0000-7000-8000-0000000000aa",
    );
  });
});
