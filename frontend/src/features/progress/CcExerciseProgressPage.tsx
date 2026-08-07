import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { Button, Page } from "@/components/ui";
import { OverrideStepModal } from "@/features/progress/OverrideStepModal";
import { ProgressionSurface } from "@/features/progress/ProgressionSurface";
import {
  formatLastSessionAt,
  standardsFromRules,
} from "@/features/progress/progressDisplay";
import { StepLadder } from "@/features/progress/StepLadder";
import { fetchCatalogCc, listProgress, overrideProgress } from "@/features/training/api";
import { ApiError } from "@/lib/api";
import {
  CC_STEP_COUNT,
  findCcProgressRow,
  joinCcCatalogWithProgress,
} from "@/lib/ccProgress";
import { errorCodeToI18nKey } from "@/lib/errors";
import type { ProgressionEvent } from "@/lib/schemas";

export function CcExerciseProgressPage() {
  const { t } = useTranslation();
  const { exerciseId = "" } = useParams();
  const qc = useQueryClient();
  const [events, setEvents] = useState<ProgressionEvent[]>([]);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);

  const progressQ = useQuery({
    queryKey: ["progress"],
    queryFn: listProgress,
  });
  const catalogQ = useQuery({
    queryKey: ["catalog", "cc"],
    queryFn: fetchCatalogCc,
  });

  const row = useMemo(() => {
    if (!catalogQ.data) return undefined;
    const rows = joinCcCatalogWithProgress(
      catalogQ.data.exercises,
      progressQ.data ?? [],
    );
    return findCcProgressRow(rows, exerciseId);
  }, [catalogQ.data, progressQ.data, exerciseId]);

  const mut = useMutation({
    mutationFn: ({ step, reason }: { step: number; reason?: string }) =>
      overrideProgress(exerciseId, step, { reason }),
    onSuccess: async (res) => {
      setEvents((e) => [...e, res.event]);
      setOverrideOpen(false);
      await qc.invalidateQueries({ queryKey: ["progress"] });
      await qc.invalidateQueries({ queryKey: ["today"] });
    },
  });

  if (progressQ.isLoading || catalogQ.isLoading) {
    return <Page title={t("progress.title")}>{t("shell.loading")}</Page>;
  }

  if (!row) {
    return (
      <Page title={t("progress.title")}>
        <p className="text-sm text-slate-600">{t("progress.exerciseNotFound")}</p>
        <Link className="mt-3 inline-block text-sm font-medium text-teal-800 underline" to="/progress">
          {t("progress.backToList")}
        </Link>
      </Page>
    );
  }

  const names = { [row.exerciseId]: row.name };

  return (
    <Page title={row.name}>
      <Link
        className="mb-2 inline-block text-sm font-medium text-teal-800 underline"
        to="/progress"
      >
        {t("progress.backToList")}
      </Link>

      <div className="rounded-xl border border-slate-200 bg-white/80 px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm text-slate-500">
              {t("progress.stepOf", {
                step: row.currentStepNumber,
                max: CC_STEP_COUNT,
              })}
              {row.currentStep?.name ? ` · ${row.currentStep.name}` : ""}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {t("progress.lastSession", {
                date: formatLastSessionAt(
                  row.lastSessionAt,
                  t("progress.lastSessionNever"),
                ),
              })}
            </p>
            {row.failStreak > 0 ? (
              <p className="mt-1 text-xs text-amber-800">
                {t("progress.failStreak", { n: row.failStreak })}
              </p>
            ) : null}
            <div className="mt-3">
              <StepLadder
                current={row.currentStepNumber}
                label={t("progress.ladderLabel", {
                  step: row.currentStepNumber,
                  max: CC_STEP_COUNT,
                })}
              />
            </div>
          </div>
          <Button variant="secondary" onClick={() => setOverrideOpen(true)}>
            {t("progress.override")}
          </Button>
        </div>
      </div>

      <h2 className="mt-4 font-display text-lg font-semibold">
        {t("progress.stepsHeading")}
      </h2>
      <ul className="mt-2 flex flex-col gap-2">
        {row.steps.map((step) => {
          const isCurrent = step.step_number === row.currentStepNumber;
          const isOpen = expanded === step.step_number || isCurrent;
          const std = standardsFromRules(step.rules);
          return (
            <li
              key={step.step_number}
              className={
                isCurrent
                  ? "rounded-xl border border-teal-600 bg-teal-50/60 px-4 py-3"
                  : "rounded-xl border border-slate-200 bg-white/80 px-4 py-3"
              }
            >
              <button
                type="button"
                className="flex w-full items-start justify-between gap-2 text-left"
                onClick={() =>
                  setExpanded((prev) =>
                    prev === step.step_number ? null : step.step_number,
                  )
                }
              >
                <span>
                  <span className="font-medium">
                    {t("progress.stepNName", {
                      n: step.step_number,
                      name: step.name,
                    })}
                  </span>
                  {isCurrent ? (
                    <span className="ml-2 text-xs font-semibold text-teal-800">
                      {t("progress.currentBadge")}
                    </span>
                  ) : null}
                </span>
                <span className="text-xs text-slate-500">
                  {isOpen ? t("progress.collapseStep") : t("progress.expandStep")}
                </span>
              </button>
              {isOpen ? (
                <div className="mt-2 flex flex-col gap-2 text-sm text-slate-700">
                  {step.description ? <p>{step.description}</p> : null}
                  {step.execution ? (
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                        {t("today.sectionExecution")}
                      </p>
                      <p>{step.execution}</p>
                    </div>
                  ) : null}
                  {step.rationale ? (
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                        {t("today.sectionRationale")}
                      </p>
                      <p>{step.rationale}</p>
                    </div>
                  ) : null}
                  {step.technique ? (
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                        {t("today.sectionTechnique")}
                      </p>
                      <p>{step.technique}</p>
                    </div>
                  ) : null}
                  <ul className="text-xs text-slate-600">
                    {std.beginner ? (
                      <li>
                        {t("today.standardBeginner")}: {std.beginner}
                      </li>
                    ) : null}
                    {std.intermediate ? (
                      <li>
                        {t("today.standardIntermediate")}: {std.intermediate}
                      </li>
                    ) : null}
                    {std.progression ? (
                      <li>
                        {t("today.standardProgression")}: {std.progression}
                      </li>
                    ) : null}
                  </ul>
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>

      <OverrideStepModal
        open={overrideOpen}
        exerciseName={row.name}
        currentStep={row.currentStepNumber}
        pending={mut.isPending}
        errorMessage={
          mut.isError
            ? mut.error instanceof ApiError
              ? t(errorCodeToI18nKey(mut.error.errorCode))
              : t("errors.generic")
            : null
        }
        onClose={() => {
          setOverrideOpen(false);
          mut.reset();
        }}
        onConfirm={(toStep, reason) => {
          mut.mutate({ step: toStep, reason: reason || undefined });
        }}
      />

      <ProgressionSurface events={events} names={names} />
    </Page>
  );
}
