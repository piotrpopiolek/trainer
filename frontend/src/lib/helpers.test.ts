import { describe, expect, it } from "vitest";

import { formatDateInTimezone, formatLocalDate, localTimezone } from "@/lib/dates";
import { errorCodeToI18nKey } from "@/lib/errors";
import { meSchema, todaySchema } from "@/lib/schemas";

describe("dates", () => {
  it("formats local YYYY-MM-DD", () => {
    expect(formatLocalDate(new Date("2026-07-28T12:00:00"))).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("formats date in timezone", () => {
    expect(formatDateInTimezone("UTC", new Date("2026-07-28T12:00:00Z"))).toBe("2026-07-28");
  });

  it("falls back on bad timezone", () => {
    expect(formatDateInTimezone("Not/AZone")).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("returns a timezone string", () => {
    expect(typeof localTimezone()).toBe("string");
    expect(localTimezone().length).toBeGreaterThan(0);
  });

  it("falls back when Intl throws", () => {
    const original = Intl.DateTimeFormat;
    // @ts-expect-error force throw path
    Intl.DateTimeFormat = () => {
      throw new Error("boom");
    };
    expect(localTimezone()).toBe("Europe/Warsaw");
    Intl.DateTimeFormat = original;
  });
});

describe("errors", () => {
  it("maps known error codes", () => {
    expect(errorCodeToI18nKey("legal_required")).toBe("errors.legalRequired");
    expect(errorCodeToI18nKey("nope")).toBe("errors.generic");
  });
});

describe("schemas", () => {
  it("parses me payload", () => {
    const me = meSchema.parse({
      schema_version: 1,
      id: "018f0000-0000-7000-8000-000000000001",
      email: "a@b.c",
      display_name: "A",
      locale: "pl-PL",
      timezone: "Europe/Warsaw",
      onboarding_completed: true,
      health_disclaimer_accepted: true,
      csrf_token: "x",
    });
    expect(me.onboarding_completed).toBe(true);
  });

  it("parses today payload", () => {
    const today = todaySchema.parse({
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
    });
    expect(today.is_rest_day).toBe(false);
  });
});
