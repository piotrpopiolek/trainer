import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import { Button, Input, Page } from "@/components/ui";
import { ProgressionSurface } from "@/features/progress/ProgressionSurface";
import {
  fetchCatalogCc,
  listProgress,
  listSatellites,
  overrideProgress,
} from "@/features/training/api";
import { ApiError } from "@/lib/api";
import { errorCodeToI18nKey } from "@/lib/errors";
import type { ProgressionEvent } from "@/lib/schemas";

export function ProgressPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const focusId = searchParams.get("adjust");
  const relatedOutcomeId = searchParams.get("relatedOutcome");
  const [events, setEvents] = useState<ProgressionEvent[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  const progressQ = useQuery({
    queryKey: ["progress"],
    queryFn: listProgress,
  });
  const catalogQ = useQuery({
    queryKey: ["catalog", "cc"],
    queryFn: fetchCatalogCc,
  });
  const satellitesQ = useQuery({
    queryKey: ["satellites"],
    queryFn: listSatellites,
  });

  const mut = useMutation({
    mutationFn: ({
      id,
      step,
      relatedOutcomeId: related,
    }: {
      id: string;
      step: number;
      relatedOutcomeId?: string;
    }) =>
      overrideProgress(id, step, {
        relatedOutcomeId: related,
      }),
    onSuccess: async (res, vars) => {
      setEvents((e) => [...e, res.event]);
      await qc.invalidateQueries({ queryKey: ["progress"] });
      await qc.invalidateQueries({ queryKey: ["today"] });
      if (vars.relatedOutcomeId) {
        setSearchParams({}, { replace: true });
      }
    },
  });

  const names = useMemo(() => {
    const map: Record<string, string> = {};
    for (const ex of catalogQ.data?.exercises ?? []) {
      map[ex.id] = ex.name;
    }
    for (const sat of satellitesQ.data ?? []) {
      map[sat.id] = sat.name;
    }
    return map;
  }, [catalogQ.data, satellitesQ.data]);

  useEffect(() => {
    if (!focusId || !progressQ.data) return;
    const row = progressQ.data.find((p) => p.exercise_id === focusId);
    if (!row) return;
    setDrafts((d) => ({
      ...d,
      [focusId]: d[focusId] ?? String(row.current_step_number),
    }));
  }, [focusId, progressQ.data]);

  if (progressQ.isLoading || catalogQ.isLoading || satellitesQ.isLoading) {
    return <Page title={t("progress.title")}>{t("shell.loading")}</Page>;
  }
  if (progressQ.isError || !progressQ.data) {
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
      {focusId ? (
        <p className="text-sm text-amber-800" role="status">
          {t("progress.adjustAfterDeleteHint", {
            name: names[focusId] ?? t("progress.unknownExercise"),
          })}
        </p>
      ) : null}
      <ul className="flex flex-col gap-3">
        {progressQ.data.map((p) => (
          <li
            key={p.exercise_id}
            className={
              focusId === p.exercise_id
                ? "rounded-xl border border-amber-400 bg-amber-50/80 px-4 py-3"
                : "rounded-xl border border-slate-200 bg-white/80 px-4 py-3"
            }
          >
            <p className="font-medium">
              {names[p.exercise_id] ?? t("progress.unknownExercise")}
            </p>
            <p className="text-xs text-slate-500">
              {t("progress.stepFail", {
                step: p.current_step_number,
                fail: p.fail_streak,
              })}
            </p>
            <div className="mt-2 flex items-end gap-2">
              <Input
                label={t("progress.toStep")}
                type="number"
                min={1}
                value={drafts[p.exercise_id] ?? String(p.current_step_number)}
                onChange={(e) =>
                  setDrafts((d) => ({ ...d, [p.exercise_id]: e.target.value }))
                }
              />
              <Button
                disabled={mut.isPending}
                onClick={() => {
                  const step = Number(drafts[p.exercise_id] ?? p.current_step_number);
                  mut.mutate({
                    id: p.exercise_id,
                    step,
                    relatedOutcomeId:
                      focusId === p.exercise_id && relatedOutcomeId
                        ? relatedOutcomeId
                        : undefined,
                  });
                }}
              >
                {t("progress.override")}
              </Button>
            </div>
          </li>
        ))}
      </ul>
      {mut.isError ? (
        <p className="text-sm text-rose-700">
          {mut.error instanceof ApiError
            ? t(errorCodeToI18nKey(mut.error.errorCode))
            : t("errors.generic")}
        </p>
      ) : null}
      <ProgressionSurface events={events} names={names} />
    </Page>
  );
}
