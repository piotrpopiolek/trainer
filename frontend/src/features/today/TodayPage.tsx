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

function goalHint(advance: unknown): string {
  if (!advance || typeof advance !== "object") return "";
  const a = advance as Record<string, unknown>;
  const sets = a.sets;
  const min = a.min_reps ?? a.reps;
  if (typeof sets === "number" && typeof min === "number") {
    return `${sets}×${min}`;
  }
  return "";
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
  } | null>(null);
  const [reps, setReps] = useState(["10", "10", "10"]);
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
                step={ex.current_step_number}
                hint={goalHint(ex.advance)}
                cacheLabel={t("sync.stepFromCache")}
                onLog={() => {
                  setReps(["10", "10", "10"]);
                  setLogExercise({
                    id: ex.exercise_id,
                    kind: "cc",
                    name: ex.name,
                    sets: 3,
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
                  setReps(["10", "10", "10"]);
                  setLogExercise({
                    id: sat.exercise_id,
                    kind: "satellite",
                    name: sat.name,
                    sets: 3,
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
                          sets: reps.map((r) => ({ reps: Number(r) || 0 })),
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
            {reps.map((r, i) => (
              <Input
                key={i}
                label={t("today.setN", { n: i + 1 })}
                type="number"
                min={0}
                value={r}
                onChange={(e) => {
                  const next = [...reps];
                  next[i] = e.target.value;
                  setReps(next);
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
  step,
  hint,
  cacheLabel,
  onLog,
}: {
  name: string;
  step: number;
  hint?: string;
  cacheLabel?: string;
  onLog: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white/80 px-4 py-3">
      <div>
        <p className="font-medium text-slate-900">{name}</p>
        <p className="text-xs text-slate-500">
          {t("today.step", { n: step })}
          {hint ? ` · ${hint}` : ""}
          {cacheLabel ? ` · ${cacheLabel}` : ""}
        </p>
      </div>
      <Button onClick={onLog}>{t("today.log")}</Button>
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
