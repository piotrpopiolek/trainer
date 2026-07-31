import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { Button, Input, Modal, Page } from "@/components/ui";
import { ProgressionSurface } from "@/features/progress/ProgressionSurface";
import { SyncStatusBanner } from "@/features/sync/SyncStatusBanner";
import {
  createSessionOfflineAware,
  softDeleteSessionOfflineAware,
} from "@/features/sync/writes";
import { fetchToday } from "@/features/training/api";
import { ApiError } from "@/lib/api";
import { formatDateInTimezone } from "@/lib/dates";
import { errorCodeToI18nKey } from "@/lib/errors";
import type { ProgressionEvent, Today } from "@/lib/schemas";
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

export function TodayPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const me = useAuthStore((s) => s.me);
  const syncEvents = useSyncStore((s) => s.recentEvents);
  const userTz = me?.timezone ?? "Europe/Warsaw";
  const [override, setOverride] = useState<number | undefined>();
  const [pendingDelete, setPendingDelete] = useState<{
    id: string;
    revision: number;
  } | null>(null);
  const [logExercise, setLogExercise] = useState<{
    id: string;
    kind: "cc" | "satellite";
    name: string;
    sets: number;
    useDuration: boolean;
  } | null>(null);
  const [setValues, setSetValues] = useState(["10", "10", "10"]);
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
    mutationFn: async (target: { id: string; revision: number }) => {
      if (!me?.id) throw new ApiError(401, "unauthorized");
      return softDeleteSessionOfflineAware(me.id, target.id, target.revision);
    },
    onSuccess: async (_result, target) => {
      setPendingDelete(null);
      qc.setQueryData<Today>(["today", override ?? null], (old) => {
        if (!old) return old;
        return {
          ...old,
          sessions: old.sessions.filter((s) => s.id !== target.id),
        };
      });
      if (navigator.onLine) {
        await qc.invalidateQueries({ queryKey: ["today"] });
      }
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
              <ExerciseRow
                key={sat.exercise_id}
                name={sat.name}
                step={sat.current_step_number ?? 1}
                onLog={() => {
                  setSetValues(["10", "10", "10"]);
                  setLogExercise({
                    id: sat.exercise_id,
                    kind: "satellite",
                    name: sat.name,
                    sets: 3,
                    useDuration: false,
                  });
                }}
              />
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
                  createMut.mutate({
                    performedAt: now.toISOString(),
                    localDate: formatDateInTimezone(userTz, now),
                    clientTimezone: userTz,
                    logs: [
                      {
                        exercise_id: logExercise.id,
                        exercise_kind: logExercise.kind,
                        section: "main",
                        sets: {
                          schema_version: 1,
                          sets: setValues.map((v) =>
                            useDuration
                              ? { duration_sec: Number(v) || 0 }
                              : { reps: Number(v) || 0 },
                          ),
                        },
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
          <div className="flex flex-col gap-2">
            {setValues.map((r, i) => (
              <Input
                key={i}
                label={
                  logExercise?.useDuration
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
            ))}
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
                onClick={() => pendingDelete && deleteMut.mutate(pendingDelete)}
              >
                {t("today.confirmDelete")}
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
