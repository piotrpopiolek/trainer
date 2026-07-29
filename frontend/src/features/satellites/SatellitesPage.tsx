import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { Button, Input, Page, Select } from "@/components/ui";
import { SyncStatusBanner } from "@/features/sync/SyncStatusBanner";
import { createSatelliteOfflineAware } from "@/features/sync/writes";
import { listSatellites } from "@/features/training/api";
import { ApiError } from "@/lib/api";
import { errorCodeToI18nKey } from "@/lib/errors";
import { useAuthStore } from "@/stores/authStore";

function scheduleKindLabel(kind: string, t: (key: string) => string): string {
  switch (kind) {
    case "daily":
      return t("satellites.scheduleDaily");
    case "weekdays":
      return t("satellites.scheduleWeekdays");
    case "category":
      return t("satellites.scheduleCategory");
    default:
      return t("satellites.scheduleUnknown");
  }
}

export function SatellitesPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const me = useAuthStore((s) => s.me);
  const [name, setName] = useState("");
  const [goalSets, setGoalSets] = useState(3);
  const [goalReps, setGoalReps] = useState(10);

  const listQ = useQuery({
    queryKey: ["satellites"],
    queryFn: listSatellites,
  });

  const createMut = useMutation({
    mutationFn: () => {
      if (!me?.id) throw new ApiError(401, "unauthorized");
      return createSatelliteOfflineAware(me.id, {
        name,
        exercise_type: "B",
        schedule_kind: "daily",
        goalSets,
        goalReps,
        stepName: t("satellites.defaultStepName"),
      });
    },
    onSuccess: async () => {
      setName("");
      await qc.invalidateQueries({ queryKey: ["satellites"] });
      await qc.invalidateQueries({ queryKey: ["today"] });
    },
  });

  const count = listQ.data?.length ?? 0;

  return (
    <>
      <SyncStatusBanner />
      <Page title={t("satellites.title")}>
        <p className="text-sm text-slate-600">
          {t("satellites.limit", { count, max: 10 })}
        </p>

        {listQ.isLoading ? <p>{t("shell.loading")}</p> : null}
        {listQ.isError ? (
          <p className="text-rose-700">
            {listQ.error instanceof ApiError
              ? t(errorCodeToI18nKey(listQ.error.errorCode))
              : t("errors.generic")}
          </p>
        ) : null}

        <ul className="flex flex-col gap-2">
          {(listQ.data ?? []).map((s) => (
            <li
              key={s.id}
              className="rounded-xl border border-slate-200 bg-white/80 px-4 py-3 text-sm"
            >
              <p className="font-medium">{s.name}</p>
              <p className="text-xs text-slate-500">
                {scheduleKindLabel(s.schedule_kind, t)} ·{" "}
                {t("satellites.steps", { n: s.steps.length })}
              </p>
            </li>
          ))}
        </ul>

        <form
          className="flex flex-col gap-3 rounded-xl border border-dashed border-slate-300 bg-white/60 p-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!name.trim() || count >= 10) return;
            createMut.mutate();
          }}
        >
          <h2 className="font-display text-lg font-semibold">
            {t("satellites.create")}
          </h2>
          <Input
            label={t("satellites.name")}
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <Select
            label={t("satellites.goalSets")}
            value={goalSets}
            onChange={(e) => setGoalSets(Number(e.target.value))}
          >
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </Select>
          <Input
            label={t("satellites.goalReps")}
            type="number"
            min={1}
            value={goalReps}
            onChange={(e) => setGoalReps(Number(e.target.value))}
          />
          {createMut.isError ? (
            <p className="text-sm text-rose-700">
              {createMut.error instanceof ApiError
                ? t(errorCodeToI18nKey(createMut.error.errorCode))
                : t("errors.generic")}
            </p>
          ) : null}
          <Button
            type="submit"
            disabled={createMut.isPending || count >= 10 || !name.trim()}
          >
            {t("satellites.submit")}
          </Button>
        </form>
      </Page>
    </>
  );
}
