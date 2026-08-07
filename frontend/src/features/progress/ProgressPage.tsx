import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";

import { Button, Page } from "@/components/ui";
import { OverrideStepModal } from "@/features/progress/OverrideStepModal";
import { ProgressionSurface } from "@/features/progress/ProgressionSurface";
import { formatLastSessionAt, formatLastSessionSummary } from "@/features/progress/progressDisplay";
import { StepLadder } from "@/features/progress/StepLadder";
import { fetchCatalogCc, listProgress, overrideProgress } from "@/features/training/api";
import { ApiError } from "@/lib/api";
import {
  CC_STEP_COUNT,
  isCcCatalogExerciseId,
  joinCcCatalogWithProgress,
  type CcProgressRow,
} from "@/lib/ccProgress";
import { errorCodeToI18nKey } from "@/lib/errors";
import type { ProgressionEvent } from "@/lib/schemas";

export function ProgressPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const focusId = searchParams.get("adjust");
  const relatedOutcomeId = searchParams.get("relatedOutcome");
  const [events, setEvents] = useState<ProgressionEvent[]>([]);
  const [overrideTarget, setOverrideTarget] = useState<CcProgressRow | null>(null);

  const progressQ = useQuery({
    queryKey: ["progress"],
    queryFn: listProgress,
  });
  const catalogQ = useQuery({
    queryKey: ["catalog", "cc"],
    queryFn: fetchCatalogCc,
  });

  const rows = useMemo(() => {
    if (!catalogQ.data) return [];
    return joinCcCatalogWithProgress(
      catalogQ.data.exercises,
      progressQ.data ?? [],
    );
  }, [catalogQ.data, progressQ.data]);

  const names = useMemo(() => {
    const map: Record<string, string> = {};
    for (const r of rows) map[r.exerciseId] = r.name;
    return map;
  }, [rows]);

  const focusIsCc =
    focusId != null &&
    catalogQ.data != null &&
    isCcCatalogExerciseId(catalogQ.data.exercises, focusId);
  const focusIsSatellite =
    focusId != null && catalogQ.data != null && !focusIsCc;

  const mut = useMutation({
    mutationFn: ({
      id,
      step,
      reason,
      relatedOutcomeId: related,
    }: {
      id: string;
      step: number;
      reason?: string;
      relatedOutcomeId?: string;
    }) =>
      overrideProgress(id, step, {
        reason,
        relatedOutcomeId: related,
      }),
    onSuccess: async (res, vars) => {
      setEvents((e) => [...e, res.event]);
      setOverrideTarget(null);
      await qc.invalidateQueries({ queryKey: ["progress"] });
      await qc.invalidateQueries({ queryKey: ["today"] });
      if (vars.relatedOutcomeId || focusId) {
        setSearchParams({}, { replace: true });
      }
    },
  });

  useEffect(() => {
    if (!focusIsCc || !focusId || rows.length === 0) return;
    const row = rows.find((r) => r.exerciseId === focusId);
    if (!row) return;
    setOverrideTarget(row);
  }, [focusIsCc, focusId, rows]);

  if (progressQ.isLoading || catalogQ.isLoading) {
    return <Page title={t("progress.title")}>{t("shell.loading")}</Page>;
  }
  if (catalogQ.isError || !catalogQ.data) {
    const code =
      catalogQ.error instanceof ApiError ? catalogQ.error.errorCode : "generic";
    return (
      <Page title={t("progress.title")}>
        <p className="text-rose-700">{t(errorCodeToI18nKey(code))}</p>
      </Page>
    );
  }
  if (progressQ.isError) {
    const code =
      progressQ.error instanceof ApiError ? progressQ.error.errorCode : "generic";
    return (
      <Page title={t("progress.title")}>
        <p className="text-rose-700">{t(errorCodeToI18nKey(code))}</p>
      </Page>
    );
  }

  return (
    <Page title={t("progress.title")}>
      <p className="text-sm text-slate-600">{t("progress.hint")}</p>
      {focusIsCc && focusId ? (
        <p className="text-sm text-amber-800" role="status">
          {t("progress.adjustAfterDeleteHint", {
            name: names[focusId] ?? t("progress.unknownExercise"),
          })}
        </p>
      ) : null}
      {focusIsSatellite ? (
        <p className="rounded-xl border border-amber-200 bg-amber-50/80 px-4 py-3 text-sm text-amber-950">
          {t("progress.satelliteAdjustHint")}{" "}
          <Link className="font-medium underline" to="/satellites">
            {t("progress.satelliteAdjustLink")}
          </Link>
        </p>
      ) : null}

      <ul className="flex flex-col gap-3">
        {rows.map((row) => {
          const focused = focusId === row.exerciseId;
          return (
            <li
              key={row.exerciseId}
              id={`progress-${row.exerciseId}`}
              className={
                focused
                  ? "rounded-xl border border-amber-400 bg-amber-50/80 px-4 py-3"
                  : "rounded-xl border border-slate-200 bg-white/80 px-4 py-3"
              }
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <Link
                    to={`/progress/${row.exerciseId}`}
                    className="font-medium text-slate-900 hover:underline"
                  >
                    {row.name}
                  </Link>
                  <p className="text-xs text-slate-500">
                    {t("progress.stepOf", {
                      step: row.currentStepNumber,
                      max: CC_STEP_COUNT,
                    })}
                    {row.currentStep?.name
                      ? ` · ${row.currentStep.name}`
                      : ""}
                    {row.failStreak > 0
                      ? ` · ${t("progress.failStreak", { n: row.failStreak })}`
                      : ""}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    {(() => {
                      const date = formatLastSessionAt(
                        row.lastSessionAt,
                        t("progress.lastSessionNever"),
                      );
                      const result = formatLastSessionSummary(
                        row.lastSessionSummary,
                        t("progress.lastSessionCompleted"),
                      );
                      return result
                        ? t("progress.lastSessionWithResult", { date, result })
                        : t("progress.lastSession", { date });
                    })()}
                  </p>
                  <div className="mt-2">
                    <StepLadder
                      current={row.currentStepNumber}
                      label={t("progress.ladderLabel", {
                        step: row.currentStepNumber,
                        max: CC_STEP_COUNT,
                      })}
                    />
                  </div>
                </div>
                <Button
                  variant="secondary"
                  onClick={() => setOverrideTarget(row)}
                >
                  {t("progress.override")}
                </Button>
              </div>
            </li>
          );
        })}
      </ul>

      <OverrideStepModal
        open={overrideTarget != null}
        exerciseName={overrideTarget?.name ?? ""}
        currentStep={overrideTarget?.currentStepNumber ?? 1}
        pending={mut.isPending}
        errorMessage={
          mut.isError
            ? mut.error instanceof ApiError
              ? t(errorCodeToI18nKey(mut.error.errorCode))
              : t("errors.generic")
            : null
        }
        onClose={() => {
          setOverrideTarget(null);
          mut.reset();
          if (focusId) setSearchParams({}, { replace: true });
        }}
        onConfirm={(toStep, reason) => {
          if (!overrideTarget) return;
          mut.mutate({
            id: overrideTarget.exerciseId,
            step: toStep,
            reason: reason || undefined,
            relatedOutcomeId:
              focusId === overrideTarget.exerciseId && relatedOutcomeId
                ? relatedOutcomeId
                : undefined,
          });
        }}
      />

      <ProgressionSurface events={events} names={names} />
    </Page>
  );
}
