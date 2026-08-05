import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { Button, Input, Modal, Page, Select } from "@/components/ui";
import { ProgressionSurface } from "@/features/progress/ProgressionSurface";
import { SyncStatusBanner } from "@/features/sync/SyncStatusBanner";
import {
  createSessionOfflineAware,
  decideSatelliteRegressionOfflineAware,
  softDeleteSessionOfflineAware,
} from "@/features/sync/writes";
import { fetchToday } from "@/features/training/api";
import { ApiError } from "@/lib/api";
import { formatDateInTimezone } from "@/lib/dates";
import { errorCodeToI18nKey } from "@/lib/errors";
import type { ProgressionEvent, Today } from "@/lib/schemas";
import { parseWeightInputToKgString } from "@/lib/satelliteContracts";
import { useAuthStore } from "@/stores/authStore";
import { useSyncStore } from "@/stores/syncStore";

type Threshold = {
  sets?: number;
  min_reps?: number | null;
  min_duration_sec?: number | null;
  require_both_sides?: boolean;
};

function formatThreshold(raw: unknown): string {
  if (!raw || typeof raw !== "object") return "";
  const a = raw as Threshold;
  const both = a.require_both_sides ? " L/P" : "";
  if (typeof a.min_duration_sec === "number") {
    const sets = typeof a.sets === "number" && a.sets > 1 ? `${a.sets}×` : "";
    return `${sets}${a.min_duration_sec}s${both}`;
  }
  if (typeof a.sets === "number" && typeof a.min_reps === "number") {
    return `${a.sets}×${a.min_reps}${both}`;
  }
  return "";
}

function advanceUsesDuration(advance: unknown): boolean {
  if (!advance || typeof advance !== "object") return false;
  return typeof (advance as Threshold).min_duration_sec === "number";
}

function defaultSetValues(advance: unknown, count: number): string[] {
  if (!advance || typeof advance !== "object") {
    return Array.from({ length: count }, () => "10");
  }
  const a = advance as Threshold;
  if (typeof a.min_duration_sec === "number") {
    return Array.from({ length: count }, () => String(a.min_duration_sec));
  }
  if (typeof a.min_reps === "number") {
    return Array.from({ length: count }, () => String(a.min_reps));
  }
  return Array.from({ length: count }, () => "10");
}

function setCountFromAdvance(advance: unknown): number {
  if (!advance || typeof advance !== "object") return 3;
  const sets = (advance as Threshold).sets;
  return typeof sets === "number" && sets >= 1 ? sets : 3;
}

type SatelliteGoal = {
  type?: string;
  sets?: number;
  min_reps?: number | null;
  min_duration_sec?: number | null;
  require_both_sides?: boolean;
};

type LogTarget = {
  id: string;
  kind: "cc" | "satellite";
  name: string;
  sets: number;
  useDuration: boolean;
  goalType?: "reps" | "duration" | "completed";
  requireBothSides?: boolean;
  trackWeight?: boolean;
  setSides?: Array<"left" | "right" | null>;
  goalSets?: number;
  goalMinReps?: number;
  goalMinDurationSec?: number;
  defaultSetValue?: string;
  configVersionId?: string;
  configHash?: string;
};

const MAX_SATELLITE_SETS = 20;

function nextSatelliteSide(
  sides: Array<"left" | "right" | null>,
  requireBothSides: boolean,
): "left" | "right" | null {
  if (!requireBothSides) return null;
  return sides[sides.length - 1] === "left" ? "right" : "left";
}

function activeMetricsList(raw: unknown): string[] {
  if (!raw || typeof raw !== "object") return [];
  const metrics = (raw as { metrics?: unknown }).metrics;
  return Array.isArray(metrics)
    ? metrics.filter((m): m is string => typeof m === "string")
    : [];
}

function formatWeightKg(raw: string): string {
  try {
    return parseWeightInputToKgString(raw);
  } catch {
    return "0.000";
  }
}

export function TodayPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const me = useAuthStore((s) => s.me);
  const syncEvents = useSyncStore((s) => s.recentEvents);
  const userTz = me?.timezone ?? "Europe/Warsaw";
  const [override, setOverride] = useState<number | undefined>();
  const [pendingDelete, setPendingDelete] = useState<{
    id: string;
    revision: number;
  } | null>(null);
  const [logExercise, setLogExercise] = useState<LogTarget | null>(null);
  const [setValues, setSetValues] = useState(["10", "10", "10"]);
  const [weightValues, setWeightValues] = useState<string[]>([]);
  const [completedFlag, setCompletedFlag] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const [events, setEvents] = useState<ProgressionEvent[]>([]);

  const todayQ = useQuery({
    queryKey: ["today", override ?? null],
    queryFn: () => fetchToday({ ccDayOverride: override }),
  });

  const createMut = useMutation({
    mutationFn: async (input: Parameters<typeof createSessionOfflineAware>[1]) => {
      if (!me?.id) throw new ApiError(401, "unauthorized");
      return createSessionOfflineAware(me.id, input);
    },
    onSuccess: async (result) => {
      if (result.pendingSync) {
        setFlash(t("sync.savedPending"));
        qc.setQueryData<Today>(["today", override ?? null], (old) => {
          if (!old) return old;
          if (old.sessions.some((s) => s.id === result.session.id)) return old;
          return { ...old, sessions: [result.session, ...old.sessions] };
        });
      } else {
        setEvents((prev) => [...prev, ...result.session.progression_events]);
        setFlash(t("today.saved"));
        await qc.invalidateQueries({ queryKey: ["today"] });
      }
      setLogExercise(null);
    },
  });

  const deleteMut = useMutation({
    mutationFn: async (input: {
      target: { id: string; revision: number };
      adjust: boolean;
    }) => {
      if (!me?.id) throw new ApiError(401, "unauthorized");
      const result = await softDeleteSessionOfflineAware(
        me.id,
        input.target.id,
        input.target.revision,
      );
      return { ...result, adjust: input.adjust, target: input.target };
    },
    onSuccess: async (result) => {
      setPendingDelete(null);
      qc.setQueryData<Today>(["today", override ?? null], (old) => {
        if (!old) return old;
        return {
          ...old,
          sessions: old.sessions.filter((s) => s.id !== result.target.id),
        };
      });
      await qc.invalidateQueries({ queryKey: ["today"] });
      if (!result.adjust) return;
      const hint = result.softDeleteOutcomeHints[0];
      if (result.pendingSync || !hint) {
        setFlash(t("today.adjustRequiresOnline"));
        return;
      }
      navigate(
        `/progress?adjust=${encodeURIComponent(hint.exercise_id)}&relatedOutcome=${encodeURIComponent(hint.related_outcome_id)}`,
      );
    },
  });

  const regressMut = useMutation({
    mutationFn: async (input: {
      exerciseId: string;
      recommendationId: string;
      decision: "accept" | "decline";
    }) => {
      if (!me?.id) throw new ApiError(401, "unauthorized");
      return decideSatelliteRegressionOfflineAware(me.id, input);
    },
    onSuccess: async (result) => {
      if (result.event) {
        setEvents((prev) => [...prev, result.event!]);
      }
      setFlash(
        result.pendingSync
          ? t("today.regressPendingSync")
          : t("today.regressDecided"),
      );
      await qc.invalidateQueries({ queryKey: ["today"] });
    },
  });

  const data = todayQ.data;
  const names = useMemo(() => {
    const map: Record<string, string> = {};
    if (!data) return map;
    for (const ex of data.cc_exercises) map[ex.exercise_id] = ex.name;
    for (const sat of data.satellites) map[sat.exercise_id] = sat.name;
    return map;
  }, [data]);

  const allEvents = [...events, ...syncEvents];

  if (todayQ.isLoading) {
    return <Page title={t("today.title")}>{t("shell.loading")}</Page>;
  }

  if (todayQ.isError || !data) {
    const code =
      todayQ.error instanceof ApiError ? todayQ.error.errorCode : "generic";
    return (
      <Page title={t("today.title")}>
        <p className="text-rose-700">{t(errorCodeToI18nKey(code))}</p>
      </Page>
    );
  }

  return (
    <>
      <SyncStatusBanner />
      <Page title={t("today.title")}>
        <p className="text-sm text-slate-600">
          {data.local_date} · {data.timezone}
          {data.is_rest_day
            ? ` · ${t("today.restDay")}`
            : ` · ${t("today.splitDay", { day: data.split_day })}`}
        </p>

        {data.is_rest_day ? (
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap gap-2">
              <span className="text-sm font-medium text-slate-700">
                {t("today.trainAnyway")}
              </span>
              {[1, 2, 3].map((d) => (
                <Button
                  key={d}
                  variant={override === d ? "primary" : "secondary"}
                  onClick={() => setOverride(d)}
                >
                  {t("today.dayN", { n: d })}
                </Button>
              ))}
              {override != null ? (
                <Button variant="ghost" onClick={() => setOverride(undefined)}>
                  {t("today.clearOverride")}
                </Button>
              ) : null}
            </div>
            {override != null ? (
              <p className="text-xs text-amber-800">{t("today.trainAnywayWarning")}</p>
            ) : null}
          </div>
        ) : null}

        {flash ? <p className="text-sm text-teal-800">{flash}</p> : null}

        <section className="flex flex-col gap-3">
          <h2 className="font-display text-lg font-semibold">{t("today.cc")}</h2>
          {data.cc_exercises.length === 0 ? (
            <p className="text-sm text-slate-500">{t("today.noCc")}</p>
          ) : (
            data.cc_exercises.map((ex) => (
              <ExerciseRow
                key={ex.exercise_id}
                name={ex.name}
                stepName={ex.step_name}
                step={ex.current_step_number}
                standards={ex.standards}
                description={ex.description}
                execution={ex.execution}
                rationale={ex.rationale}
                technique={ex.technique}
                cacheLabel={t("sync.stepFromCache")}
                onLog={() => {
                  const sets = setCountFromAdvance(ex.advance);
                  const useDuration = advanceUsesDuration(ex.advance);
                  setSetValues(defaultSetValues(ex.advance, sets));
                  setLogExercise({
                    id: ex.exercise_id,
                    kind: "cc",
                    name: ex.name,
                    sets,
                    useDuration,
                  });
                }}
              />
            ))
          )}
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="font-display text-lg font-semibold">{t("today.satellites")}</h2>
          {data.satellites.length === 0 ? (
            <p className="text-sm text-slate-500">{t("today.noSatellites")}</p>
          ) : (
            data.satellites.map((sat) => (
              <div key={sat.exercise_id} className="flex flex-col gap-2">
                <ExerciseRow
                  name={sat.name}
                  stepName={sat.step_name}
                  step={sat.current_step_number ?? 1}
                  onLog={() => {
                    const goal = (sat.goal ?? {}) as SatelliteGoal;
                    const metrics = activeMetricsList(sat.active_metrics);
                    const goalType =
                      goal.type === "completed"
                        ? "completed"
                        : goal.type === "duration"
                          ? "duration"
                          : "reps";
                    const requireBothSides = Boolean(goal.require_both_sides);
                    const goalSets =
                      typeof goal.sets === "number" && goal.sets >= 1 ? goal.sets : 3;
                    const defaultVal =
                      goalType === "duration"
                        ? String(goal.min_duration_sec ?? 30)
                        : String(goal.min_reps ?? 10);
                    const trackWeight = metrics.includes("weight_kg");
                    const initialSides: Array<"left" | "right" | null> =
                      goalType === "completed"
                        ? []
                        : [requireBothSides ? "left" : null];
                    setCompletedFlag(false);
                    setSetValues(goalType === "completed" ? [] : [defaultVal]);
                    setWeightValues(
                      trackWeight && goalType !== "completed" ? ["20"] : [],
                    );
                    setLogExercise({
                      id: sat.exercise_id,
                      kind: "satellite",
                      name: sat.name,
                      sets: initialSides.length || 1,
                      useDuration: goalType === "duration",
                      goalType,
                      requireBothSides,
                      trackWeight,
                      setSides: initialSides,
                      goalSets,
                      goalMinReps:
                        typeof goal.min_reps === "number" ? goal.min_reps : undefined,
                      goalMinDurationSec:
                        typeof goal.min_duration_sec === "number"
                          ? goal.min_duration_sec
                          : undefined,
                      defaultSetValue: defaultVal,
                      configVersionId: sat.config_version_id ?? undefined,
                      configHash: sat.config_hash ?? undefined,
                    });
                  }}
                />
                {sat.pending_regression ? (
                  <div className="rounded-xl border border-amber-200 bg-amber-50/80 px-4 py-3 text-sm text-amber-950">
                    <p className="font-medium">{t("today.regressSuggestTitle")}</p>
                    <p className="mt-1">
                      {t("today.regressSuggestBody", {
                        name: sat.name,
                        from: sat.pending_regression.from_step,
                        to: sat.pending_regression.to_step,
                      })}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button
                        disabled={regressMut.isPending}
                        onClick={() =>
                          regressMut.mutate({
                            exerciseId: sat.exercise_id,
                            recommendationId: sat.pending_regression!.id,
                            decision: "accept",
                          })
                        }
                      >
                        {t("today.regressAccept")}
                      </Button>
                      <Button
                        variant="secondary"
                        disabled={regressMut.isPending}
                        onClick={() =>
                          regressMut.mutate({
                            exerciseId: sat.exercise_id,
                            recommendationId: sat.pending_regression!.id,
                            decision: "decline",
                          })
                        }
                      >
                        {t("today.regressDecline")}
                      </Button>
                    </div>
                  </div>
                ) : null}
              </div>
            ))
          )}
        </section>

        <SessionsList
          data={data}
          onDelete={(id, revision) => setPendingDelete({ id, revision })}
          tDelete={t("today.deleteSession")}
          tSessions={t("today.sessions")}
          tEmpty={t("today.noSessions")}
        />

        <Modal
          open={logExercise != null}
          title={logExercise ? t("today.logTitle", { name: logExercise.name }) : ""}
          onClose={() => setLogExercise(null)}
          actions={
            <>
              <Button variant="secondary" onClick={() => setLogExercise(null)}>
                {t("common.cancel")}
              </Button>
              <Button
                disabled={createMut.isPending || !logExercise}
                onClick={() => {
                  if (!logExercise) return;
                  const now = new Date();
                  const useDuration = logExercise.useDuration;
                  const isSatellite = logExercise.kind === "satellite";
                  let setsPayload:
                    | {
                        schema_version: number;
                        completed?: boolean | null;
                        sets: Array<{
                          reps?: number;
                          duration_sec?: number;
                          weight_kg?: string;
                          sides?: "left" | "right" | "bilateral";
                        }>;
                      }
                    | undefined;
                  if (isSatellite && logExercise.goalType === "completed") {
                    setsPayload = {
                      schema_version: 1,
                      completed: completedFlag,
                      sets: [],
                    };
                  } else if (isSatellite) {
                    setsPayload = {
                      schema_version: 1,
                      completed: null,
                      sets: setValues.map((v, i) => {
                        const side = logExercise.setSides?.[i] ?? null;
                        const row: {
                          reps?: number;
                          duration_sec?: number;
                          weight_kg?: string;
                          sides?: "left" | "right" | "bilateral";
                        } = useDuration
                          ? { duration_sec: Number(v) || 0 }
                          : { reps: Number(v) || 0 };
                        if (side) row.sides = side;
                        if (logExercise.trackWeight) {
                          row.weight_kg = formatWeightKg(weightValues[i] ?? "0");
                        }
                        return row;
                      }),
                    };
                  } else {
                    setsPayload = {
                      schema_version: 1,
                      sets: setValues.map((v) =>
                        useDuration
                          ? { duration_sec: Number(v) || 0 }
                          : { reps: Number(v) || 0 },
                      ),
                    };
                  }
                  createMut.mutate({
                    performedAt: now.toISOString(),
                    localDate: formatDateInTimezone(userTz, now),
                    clientTimezone: userTz,
                    logs: [
                      {
                        exercise_id: logExercise.id,
                        exercise_kind: logExercise.kind,
                        section: isSatellite ? "accessories" : "main",
                        sets: setsPayload,
                        ...(isSatellite &&
                        logExercise.configVersionId &&
                        logExercise.configHash
                          ? {
                              satellite_config_version_id:
                                logExercise.configVersionId,
                              satellite_config_hash: logExercise.configHash,
                            }
                          : {}),
                      },
                    ],
                  });
                }}
              >
                {t("today.saveLog")}
              </Button>
            </>
          }
        >
          <div className="flex flex-col gap-3">
            {logExercise?.kind === "satellite" &&
            logExercise.goalType &&
            logExercise.goalType !== "completed" &&
            logExercise.goalSets ? (
              <p className="text-sm text-slate-600">
                {logExercise.goalType === "duration"
                  ? t("today.goalHintDuration", {
                      sets: logExercise.goalSets,
                      sec: logExercise.goalMinDurationSec ?? "—",
                      sides: logExercise.requireBothSides
                        ? t("today.goalHintSides")
                        : "",
                    })
                  : t("today.goalHintReps", {
                      sets: logExercise.goalSets,
                      reps: logExercise.goalMinReps ?? "—",
                      sides: logExercise.requireBothSides
                        ? t("today.goalHintSides")
                        : "",
                    })}
              </p>
            ) : null}
            {logExercise?.goalType === "completed" ? (
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={completedFlag}
                  onChange={(e) => setCompletedFlag(e.target.checked)}
                />
                {t("today.markCompleted")}
              </label>
            ) : (
              <>
                {setValues.map((r, i) => {
                  const side = logExercise?.setSides?.[i];
                  const sideLabel =
                    side === "left"
                      ? t("today.sideLeft")
                      : side === "right"
                        ? t("today.sideRight")
                        : null;
                  const isSatelliteSets = logExercise?.kind === "satellite";
                  return (
                    <div key={i} className="flex flex-col gap-1">
                      <Input
                        label={
                          !isSatelliteSets && sideLabel
                            ? t("today.setSideN", { n: i + 1, side: sideLabel })
                            : logExercise?.useDuration
                              ? t("today.setDurationN", { n: i + 1 })
                              : t("today.setN", { n: i + 1 })
                        }
                        type="number"
                        min={0}
                        value={r}
                        onChange={(e) => {
                          const next = [...setValues];
                          next[i] = e.target.value;
                          setSetValues(next);
                        }}
                      />
                      {isSatelliteSets && logExercise.requireBothSides ? (
                        <Select
                          label={t("today.sideLabelN", { n: i + 1 })}
                          value={side ?? "left"}
                          onChange={(e) => {
                            const nextSide = e.target.value as "left" | "right";
                            setLogExercise((prev) => {
                              if (!prev?.setSides) return prev;
                              const setSides = [...prev.setSides];
                              setSides[i] = nextSide;
                              return { ...prev, setSides };
                            });
                          }}
                        >
                          <option value="left">{t("today.sideLeft")}</option>
                          <option value="right">{t("today.sideRight")}</option>
                        </Select>
                      ) : null}
                      {logExercise?.trackWeight ? (
                        <Input
                          label={t("today.weightKg")}
                          type="number"
                          min={0}
                          step="0.001"
                          value={weightValues[i] ?? ""}
                          onChange={(e) => {
                            const next = [...weightValues];
                            next[i] = e.target.value;
                            setWeightValues(next);
                          }}
                        />
                      ) : null}
                      {isSatelliteSets && setValues.length > 1 ? (
                        <Button
                          type="button"
                          variant="ghost"
                          onClick={() => {
                            setSetValues((prev) =>
                              prev.filter((_, idx) => idx !== i),
                            );
                            setWeightValues((prev) =>
                              prev.filter((_, idx) => idx !== i),
                            );
                            setLogExercise((prev) => {
                              if (!prev) return prev;
                              const setSides = (prev.setSides ?? []).filter(
                                (_, idx) => idx !== i,
                              );
                              return {
                                ...prev,
                                setSides,
                                sets: Math.max(1, setSides.length),
                              };
                            });
                          }}
                        >
                          {t("today.removeSet", { n: i + 1 })}
                        </Button>
                      ) : null}
                    </div>
                  );
                })}
                {logExercise?.kind === "satellite" ? (
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={setValues.length >= MAX_SATELLITE_SETS}
                    onClick={() => {
                      const defaultVal =
                        logExercise.defaultSetValue ??
                        (logExercise.useDuration ? "20" : "10");
                      const nextSide = nextSatelliteSide(
                        logExercise.setSides ?? [],
                        Boolean(logExercise.requireBothSides),
                      );
                      setSetValues((prev) => [...prev, defaultVal]);
                      if (logExercise.trackWeight) {
                        setWeightValues((prev) => [...prev, "20"]);
                      }
                      setLogExercise({
                        ...logExercise,
                        setSides: [...(logExercise.setSides ?? []), nextSide],
                        sets: setValues.length + 1,
                      });
                    }}
                  >
                    {t("today.addSet")}
                  </Button>
                ) : null}
              </>
            )}
            {createMut.isError ? (
              <p className="text-sm text-rose-700" role="alert">
                {createMut.error instanceof ApiError
                  ? t(errorCodeToI18nKey(createMut.error.errorCode))
                  : t("errors.generic")}
              </p>
            ) : null}
          </div>
        </Modal>

        <Modal
          open={pendingDelete != null}
          title={t("today.noRewindTitle")}
          onClose={() => setPendingDelete(null)}
          actions={
            <>
              <Button variant="secondary" onClick={() => setPendingDelete(null)}>
                {t("common.cancel")}
              </Button>
              <Button
                variant="danger"
                disabled={deleteMut.isPending || !pendingDelete}
                onClick={() =>
                  pendingDelete &&
                  deleteMut.mutate({ target: pendingDelete, adjust: false })
                }
              >
                {t("today.confirmDelete")}
              </Button>
              <Button
                disabled={deleteMut.isPending || !pendingDelete}
                onClick={() =>
                  pendingDelete &&
                  deleteMut.mutate({ target: pendingDelete, adjust: true })
                }
              >
                {t("today.confirmDeleteAndAdjust")}
              </Button>
            </>
          }
        >
          <p>{t("today.noRewindBody")}</p>
        </Modal>

        <ProgressionSurface events={allEvents} names={names} />
      </Page>
    </>
  );
}

function ExerciseRow({
  name,
  stepName,
  step,
  standards,
  description,
  execution,
  rationale,
  technique,
  cacheLabel,
  onLog,
}: {
  name: string;
  stepName?: string | null;
  step: number;
  standards?: {
    beginner?: unknown;
    intermediate?: unknown;
    progression?: unknown;
  } | null;
  description?: string | null;
  execution?: string | null;
  rationale?: string | null;
  technique?: string | null;
  cacheLabel?: string;
  onLog: () => void;
}) {
  const { t } = useTranslation();
  const beg = formatThreshold(standards?.beginner);
  const mid = formatThreshold(standards?.intermediate);
  const prog = formatThreshold(standards?.progression);
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-slate-200 bg-white/80 px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-medium text-slate-900">{name}</p>
          <p className="text-xs text-slate-500">
            {t("today.step", { n: step })}
            {stepName ? ` · ${stepName}` : ""}
            {cacheLabel ? ` · ${cacheLabel}` : ""}
          </p>
        </div>
        <Button onClick={onLog}>{t("today.log")}</Button>
      </div>
      {beg || mid || prog ? (
        <ul className="text-xs text-slate-600">
          {beg ? (
            <li>
              {t("today.standardBeginner")}: {beg}
            </li>
          ) : null}
          {mid ? (
            <li>
              {t("today.standardIntermediate")}: {mid}
            </li>
          ) : null}
          {prog ? (
            <li>
              {t("today.standardProgression")}: {prog}
            </li>
          ) : null}
        </ul>
      ) : null}
      {description ? <p className="text-sm text-slate-700">{description}</p> : null}
      {execution || rationale || technique ? (
        <details className="text-sm text-slate-600">
          <summary className="cursor-pointer text-slate-800">
            {t("today.stepDetails")}
          </summary>
          <div className="mt-2 flex flex-col gap-2">
            {execution ? (
              <p>
                <span className="font-medium">{t("today.sectionExecution")}: </span>
                {execution}
              </p>
            ) : null}
            {rationale ? (
              <p>
                <span className="font-medium">{t("today.sectionRationale")}: </span>
                {rationale}
              </p>
            ) : null}
            {technique ? (
              <p>
                <span className="font-medium">{t("today.sectionTechnique")}: </span>
                {technique}
              </p>
            ) : null}
          </div>
        </details>
      ) : null}
    </div>
  );
}

function SessionsList({
  data,
  onDelete,
  tDelete,
  tSessions,
  tEmpty,
}: {
  data: Today;
  onDelete: (id: string, revision: number) => void;
  tDelete: string;
  tSessions: string;
  tEmpty: string;
}) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="font-display text-lg font-semibold">{tSessions}</h2>
      {data.sessions.length === 0 ? (
        <p className="text-sm text-slate-500">{tEmpty}</p>
      ) : (
        data.sessions.map((s) => (
          <div
            key={s.id}
            className="rounded-xl border border-slate-200 bg-white/80 px-4 py-3 text-sm"
          >
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="font-medium">{s.local_date}</p>
                <ul className="mt-1 text-slate-600">
                  {s.logs.map((l) => (
                    <li key={l.id}>
                      {l.exercise_name_snapshot}
                      {l.goal_met ? " ✓" : ""}
                    </li>
                  ))}
                </ul>
              </div>
              <Button variant="ghost" onClick={() => onDelete(s.id, s.revision)}>
                {tDelete}
              </Button>
            </div>
          </div>
        ))
      )}
    </section>
  );
}
