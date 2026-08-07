/** Vitest — catalog × progress join for Big Six overview. */

import { describe, expect, it } from "vitest";

import {
  findCcProgressRow,
  isCcCatalogExerciseId,
  joinCcCatalogWithProgress,
} from "@/lib/ccProgress";
import type { CatalogCcExercise, ProgressItem } from "@/lib/schemas";

function step(n: number, name: string) {
  return {
    schema_version: 1,
    step_number: n,
    name,
    description: "",
    execution: "",
    rationale: "",
    technique: "",
    content_status: "ready",
    rules: {},
  };
}

const catalog: CatalogCcExercise[] = [
  {
    schema_version: 1,
    id: "018f0000-0000-7000-8000-0000000000a1",
    slug: "push_ups",
    name: "Pompki",
    description: null,
    exercise_type: "A",
    steps: [step(1, "Pion"), step(2, "Kolana")],
  },
  {
    schema_version: 1,
    id: "018f0000-0000-7000-8000-0000000000a2",
    slug: "squats",
    name: "Przysiady",
    description: null,
    exercise_type: "A",
    steps: [step(1, "Krzesło"), step(2, "Pełne")],
  },
];

describe("joinCcCatalogWithProgress", () => {
  it("returns one row per catalog exercise and ignores satellite progress", () => {
    const progress: ProgressItem[] = [
      {
        schema_version: 1,
        exercise_id: "018f0000-0000-7000-8000-0000000000a1",
        current_step_number: 3,
        fail_streak: 1,
        last_session_at: "2026-08-01T10:00:00Z",
        is_active: true,
      },
      {
        schema_version: 1,
        exercise_id: "018f0000-0000-7000-8000-000000000099",
        current_step_number: 2,
        fail_streak: 0,
        is_active: true,
      },
    ];
    const rows = joinCcCatalogWithProgress(catalog, progress);
    expect(rows).toHaveLength(2);
    expect(rows[0]?.currentStepNumber).toBe(3);
    expect(rows[0]?.failStreak).toBe(1);
    expect(rows[0]?.currentStep?.name).toBe("Pion"); // step 3 absent → fall back to first
    expect(rows[1]?.currentStepNumber).toBe(1);
    expect(rows[1]?.hasProgress).toBe(false);
    expect(findCcProgressRow(rows, catalog[0]!.id)?.name).toBe("Pompki");
    expect(isCcCatalogExerciseId(catalog, catalog[0]!.id)).toBe(true);
    expect(isCcCatalogExerciseId(catalog, "018f0000-0000-7000-8000-000000000099")).toBe(
      false,
    );
  });

  it("resolves current step name from catalog", () => {
    const progress: ProgressItem[] = [
      {
        schema_version: 1,
        exercise_id: catalog[1]!.id,
        current_step_number: 2,
        fail_streak: 0,
        is_active: true,
      },
    ];
    const rows = joinCcCatalogWithProgress(catalog, progress);
    expect(rows[1]?.currentStep?.name).toBe("Pełne");
  });
});
