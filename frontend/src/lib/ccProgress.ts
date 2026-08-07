/** Join CC catalog exercises with server progress (US-017). */

import type { CatalogCcExercise, CatalogCcStep, ProgressItem } from "@/lib/schemas";

export type { CatalogCcExercise, CatalogCcStep };

export const CC_STEP_COUNT = 10;

export type CcProgressRow = {
  exerciseId: string;
  slug: string | null;
  name: string;
  description: string | null;
  steps: CatalogCcStep[];
  currentStepNumber: number;
  failStreak: number;
  lastSessionAt: string | null;
  lastSessionSummary: string | null;
  isActive: boolean;
  currentStep: CatalogCcStep | null;
  hasProgress: boolean;
};

/** Always one row per catalog exercise; progress missing → step 1 defaults. */
export function joinCcCatalogWithProgress(
  exercises: CatalogCcExercise[],
  progress: ProgressItem[],
): CcProgressRow[] {
  const byId = new Map(progress.map((p) => [p.exercise_id, p]));
  return exercises.map((ex) => {
    const p = byId.get(ex.id);
    const currentStepNumber = p?.current_step_number ?? 1;
    const steps = [...ex.steps].sort((a, b) => a.step_number - b.step_number);
    const currentStep =
      steps.find((s) => s.step_number === currentStepNumber) ?? steps[0] ?? null;
    return {
      exerciseId: ex.id,
      slug: ex.slug,
      name: ex.name,
      description: ex.description ?? null,
      steps,
      currentStepNumber,
      failStreak: p?.fail_streak ?? 0,
      lastSessionAt: p?.last_session_at ?? null,
      lastSessionSummary: p?.last_session_summary ?? null,
      isActive: p?.is_active ?? true,
      currentStep,
      hasProgress: p != null,
    };
  });
}

export function findCcProgressRow(
  rows: CcProgressRow[],
  exerciseId: string,
): CcProgressRow | undefined {
  return rows.find((r) => r.exerciseId === exerciseId);
}

export function isCcCatalogExerciseId(
  exercises: CatalogCcExercise[],
  exerciseId: string,
): boolean {
  return exercises.some((e) => e.id === exerciseId);
}
