import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { Button, Input, Page } from "@/components/ui";
import { ProgressionSurface } from "@/features/progress/ProgressionSurface";
import { fetchToday, overrideProgress } from "@/features/training/api";
import { ApiError } from "@/lib/api";
import { errorCodeToI18nKey } from "@/lib/errors";
import type { ProgressionEvent } from "@/lib/schemas";

export function ProgressPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [events, setEvents] = useState<ProgressionEvent[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  const todayQ = useQuery({
    queryKey: ["today", null],
    queryFn: () => fetchToday(),
  });

  const mut = useMutation({
    mutationFn: ({ id, step }: { id: string; step: number }) =>
      overrideProgress(id, step),
    onSuccess: async (res) => {
      setEvents((e) => [...e, res.event]);
      await qc.invalidateQueries({ queryKey: ["today"] });
    },
  });

  if (todayQ.isLoading) {
    return <Page title={t("progress.title")}>{t("shell.loading")}</Page>;
  }
  if (todayQ.isError || !todayQ.data) {
    const code =
      todayQ.error instanceof ApiError ? todayQ.error.errorCode : "generic";
    return (
      <Page title={t("progress.title")}>
        <p className="text-rose-700">{t(errorCodeToI18nKey(code))}</p>
      </Page>
    );
  }

  const names: Record<string, string> = {};
  for (const ex of todayQ.data.cc_exercises) names[ex.exercise_id] = ex.name;
  for (const p of todayQ.data.progress) {
    if (!names[p.exercise_id]) names[p.exercise_id] = p.exercise_id.slice(0, 8);
  }

  return (
    <Page title={t("progress.title")}>
      <p className="text-sm text-slate-600">{t("progress.hint")}</p>
      <ul className="flex flex-col gap-3">
        {todayQ.data.progress.map((p) => (
          <li
            key={p.exercise_id}
            className="rounded-xl border border-slate-200 bg-white/80 px-4 py-3"
          >
            <p className="font-medium">{names[p.exercise_id]}</p>
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
                  mut.mutate({ id: p.exercise_id, step });
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
