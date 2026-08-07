import { describe, expect, it } from "vitest";

import {
  formatLastSessionAt,
  formatLastSessionSummary,
  standardsFromRules,
} from "@/features/progress/progressDisplay";

describe("progressDisplay", () => {
  it("formats standards from rules.standards", () => {
    const std = standardsFromRules({
      schema_version: 2,
      standards: {
        beginner: { sets: 1, min_reps: 8 },
        intermediate: { sets: 2, min_reps: 15 },
        progression: { sets: 3, min_reps: 30 },
      },
    });
    expect(std.beginner).toBe("1×8");
    expect(std.intermediate).toBe("2×15");
    expect(std.progression).toBe("3×30");
  });

  it("formats last session or empty label", () => {
    expect(formatLastSessionAt(null, "brak")).toBe("brak");
    expect(formatLastSessionAt("not-a-date", "brak")).toBe("brak");
    expect(formatLastSessionAt("2026-08-01T10:00:00Z", "brak")).toMatch(/2026/);
  });

  it("maps completed summary for i18n", () => {
    expect(formatLastSessionSummary("3×10", "wykonane")).toBe("3×10");
    expect(formatLastSessionSummary("completed", "wykonane")).toBe("wykonane");
    expect(formatLastSessionSummary(null, "wykonane")).toBeNull();
  });
});
