import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { Button, Page } from "@/components/ui";
import { MeasurementRangeToggle } from "@/features/measurements/MeasurementRangeToggle";
import type { RangeDays } from "@/features/measurements/measurementSeries";
import { OverrideStepModal } from "@/features/progress/OverrideStepModal";
import { ProgressionSurface } from "@/features/progress/ProgressionSurface";
import { StepLadder } from "@/features/progress/StepLadder";
import {
  activeMetricNames,
  scheduleLabelKey,
  weekdayLabelKeys,
} from "@/features/progress/satelliteSchedule";
import {
  buildSatelliteTrendSeries,
  completedDatesInRange,
} from "@/features/progress/satelliteSeries";
import { SatelliteTrendChart } from "@/features/progress/SatelliteTrendChart";
import {
  getSatelliteProgressCached,
  listSatelliteProgressCached,
} from "@/features/progress/satelliteProgressCache";
import { overrideProgress } from "@/features/training/api";
import { ApiError } from "@/lib/api";
import { formatDateInTimezone } from "@/lib/dates";
import { errorCodeToI18nKey } from "@/lib/errors";
import type { ProgressionEvent } from "@/lib/schemas";
import { useAuthStore } from "@/stores/authStore";

export function SatelliteExerciseProgressPage() {
  const { t } = useTranslation();
  const { exerciseId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const qc = useQueryClient();
  const me = useAuthStore((s) => s.me);
  const userId = me?.id;
  const tz = me?.timezone ?? "Europe/Warsaw";
  const todayLocalDate = formatDateInTimezone(tz, new Date());
  const [rangeDays, setRangeDays] = useState<RangeDays>(30);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [events, setEvents] = useState<ProgressionEvent[]>([]);
  const [relatedOutcomeId, setRelatedOutcomeId] = useState<string | null>(
    () => searchParams.get("relatedOutcome"),
  );

  const listQ = useQuery({
    queryKey: ["satellite-progress"],
    queryFn: () => listSatelliteProgressCached(userId!),
    enabled: !!userId,
  });

  const detailQ = useQuery({
    queryKey: ["satellite-progress", exerciseId],
    queryFn: () => getSatelliteProgressCached(userId!, exerciseId),
    enabled: !!userId && !!exerciseId,
  });

  const item = detailQ.data ?? listQ.data?.find((i) => i.id === exerciseId);

  useEffect(() => {
    if (searchParams.get("adjust") === exerciseId && item) {
      const related = searchParams.get("relatedOutcome");
      if (related) setRelatedOutcomeId(related);
      if (item.progression?.mode === "steps") {
        setOverrideOpen(true);
      }
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, exerciseId, item, setSearchParams]);

  const metrics = useMemo(
    () => activeMetricNames(item?.active_metrics),
    [item?.active_metrics],
  );

  const series = useMemo(() => {
    if (!item || item.exercise_type === "C") return [];
    return buildSatelliteTrendSeries(
      item.points,
      metrics,
      rangeDays,
      todayLocalDate,
    );
  }, [item, metrics, rangeDays, todayLocalDate]);

  const completedDates = useMemo(() => {
    if (!item || item.exercise_type !== "C") return [];
    return completedDatesInRange(item.points, rangeDays, todayLocalDate);
  }, [item, rangeDays, todayLocalDate]);

  const mut = useMutation({
    mutationFn: ({
      step,
      reason,
      relatedOutcomeId: related,
    }: {
      step: number;
      reason?: string;
      relatedOutcomeId?: string;
    }) =>
      overrideProgress(exerciseId, step, {
        reason,
        relatedOutcomeId: related,
      }),
    onSuccess: async (res) => {
      setEvents((e) => [...e, res.event]);
      setOverrideOpen(false);
      await qc.invalidateQueries({ queryKey: ["satellite-progress"] });
      await qc.invalidateQueries({ queryKey: ["progress"] });
      await qc.invalidateQueries({ queryKey: ["today"] });
    },
  });

  if (listQ.isLoading || detailQ.isLoading) {
    return <Page title={t("satProgress.title")}>{t("shell.loading")}</Page>;
  }

  if (!item) {
    return (
      <Page title={t("satProgress.title")}>
        <p className="text-sm text-slate-600">{t("satProgress.notFound")}</p>
        <Link
          className="mt-3 inline-block text-sm font-medium text-teal-800 underline"
          to="/sat-progress"
        >
          {t("satProgress.backToList")}
        </Link>
      </Page>
    );
  }

  const schedule = scheduleLabelKey(item);
  const scheduleText = schedule.weekdays
    ? weekdayLabelKeys(schedule.weekdays)
        .map((k) => t(k))
        .join("/")
    : t(schedule.key);

  const isSteps = item.progression?.mode === "steps";
  const stepMax = Math.max(1, item.steps_count || 1);

  return (
    <Page title={item.name}>
      <Link
        className="text-sm font-medium text-teal-800 underline"
        to="/sat-progress"
      >
        {t("satProgress.backToList")}
      </Link>

      <p className="text-sm text-slate-600">{scheduleText}</p>

      {isSteps ? (
        <div className="flex flex-col gap-2 rounded-xl border border-slate-200 bg-white/80 px-4 py-3">
          <p className="text-sm text-slate-700">
            {t("satProgress.stepOf", {
              step: item.current_step_number,
              max: stepMax,
            })}
            {item.current_step_name
              ? t("satProgress.stepName", { name: item.current_step_name })
              : null}
          </p>
          <StepLadder
            current={item.current_step_number}
            max={stepMax}
            label={t("satProgress.ladderAria", { name: item.name })}
          />
          <Button
            type="button"
            variant="secondary"
            className="self-start"
            onClick={() => setOverrideOpen(true)}
          >
            {t("progress.override")}
          </Button>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-lg font-semibold">
          {t("satProgress.trendsTitle")}
        </h2>
        <MeasurementRangeToggle value={rangeDays} onChange={setRangeDays} />
      </div>

      {item.exercise_type === "C" ? (
        completedDates.length === 0 ? (
          <p className="text-sm text-slate-500">{t("satProgress.trendsEmpty")}</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {completedDates.map((d) => (
              <li
                key={d}
                className="rounded-xl border border-slate-200 bg-white/80 px-4 py-2 text-sm"
              >
                {t("satProgress.completedOn", { date: d })}
              </li>
            ))}
          </ul>
        )
      ) : series.length === 0 ? (
        <p className="text-sm text-slate-500">{t("satProgress.trendsEmpty")}</p>
      ) : (
        <div className="flex flex-col gap-3">
          {series.map((s) => (
            <SatelliteTrendChart key={`${s.metric}-${s.side}`} series={s} />
          ))}
        </div>
      )}

      <ProgressionSurface events={events} names={{ [item.id]: item.name }} />

      <OverrideStepModal
        open={overrideOpen}
        exerciseName={item.name}
        currentStep={item.current_step_number}
        maxStep={stepMax}
        onClose={() => setOverrideOpen(false)}
        pending={mut.isPending}
        errorMessage={
          mut.isError
            ? mut.error instanceof ApiError
              ? t(errorCodeToI18nKey(mut.error.errorCode))
              : t("errors.generic")
            : null
        }
        onConfirm={(toStep, reason) =>
          mut.mutate({
            step: toStep,
            reason: reason || undefined,
            relatedOutcomeId: relatedOutcomeId || undefined,
          })
        }
      />
    </Page>
  );
}
