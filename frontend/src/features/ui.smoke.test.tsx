import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { LoginPage } from "@/features/auth/pages";
import { ProgressionSurface } from "@/features/progress/ProgressionSurface";
import { ConflictSurface } from "@/features/sync/ConflictSurface";
import { SyncStatusBanner } from "@/features/sync/SyncStatusBanner";
import "@/lib/i18n";
import { useAuthStore } from "@/stores/authStore";
import { useSeenEventsStore } from "@/stores/seenEventsStore";
import { useSyncStore } from "@/stores/syncStore";

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
              schema_version: 1,
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
    expect(screen.queryByRole("heading", { name: "Awans!" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "OK" })).not.toBeInTheDocument();
  });
});

describe("ConflictSurface (FR-073a)", () => {
  beforeEach(() => {
    useSyncStore.getState().reset();
    useAuthStore.getState().setMe({
      schema_version: 1,
      id: "018f0000-0000-7000-8000-000000000001",
      email: "a@b.c",
      display_name: null,
      locale: "pl-PL",
      timezone: "Europe/Warsaw",
      onboarding_completed: true,
      health_disclaimer_accepted: true,
      csrf_token: "csrf",
    });
    useSyncStore.setState({
      modalConflictQueue: [
        {
          id: "018f0000-0000-7000-8000-0000000000cf",
          entity_type: "workout_session",
          entity_id: "018f0000-0000-7000-8000-0000000000se",
          conflict_kind: "conflict_tie",
          created_at: "2026-08-10T12:00:00Z",
          acknowledged: false,
          winning_revision: 2,
          losing_payload: {
            schema_version: 1,
            op: "upsert",
            revision: 2,
            payload: {
              schema_version: 1,
              local_date: "2026-08-10",
              performed_at: "2026-08-10T10:00:00Z",
              logs: [],
            },
          },
        },
      ],
    });
  });

  it("shows mandatory tie modal with recover CTA", () => {
    render(
      <MemoryRouter>
        <ConflictSurface />
      </MemoryRouter>,
    );
    expect(screen.getByText("Konflikt synchronizacji")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Zapisz przegraną jako nową" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Zostaw wersję serwera" }),
    ).toBeInTheDocument();
  });
});

describe("SyncStatusBanner (dogfood)", () => {
  beforeEach(() => {
    useSyncStore.getState().reset();
    useAuthStore.getState().setMe({
      schema_version: 1,
      id: "018f0000-0000-7000-8000-000000000001",
      email: "a@b.c",
      display_name: null,
      locale: "pl-PL",
      timezone: "Europe/Warsaw",
      onboarding_completed: true,
      health_disclaimer_accepted: true,
      csrf_token: "csrf",
    });
  });

  it("links quarantine badge to settings without crashing", () => {
    useSyncStore.setState({
      quarantine: 2,
      pending: 0,
      conflicts: [],
      quarantineItems: [],
    });
    render(
      <MemoryRouter>
        <SyncStatusBanner />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Wymaga uwagi: 2/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Otwórz kwarantannę" }),
    ).toHaveAttribute("href", "/settings");
  });
});
