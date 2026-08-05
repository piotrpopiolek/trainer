import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { Button, Input, Page, Select } from "@/components/ui";
import { SyncStatusBanner } from "@/features/sync/SyncStatusBanner";
import { createSatelliteOfflineAware, createSatellitePresetOfflineAware } from "@/features/sync/writes";
import { cloneSatellite, listSatellites, updateSatellite } from "@/features/training/api";
import { ApiError } from "@/lib/api";
import { errorCodeToI18nKey } from "@/lib/errors";
import type { Satellite } from "@/lib/schemas";
import {
  SATELLITE_PRESET_IDS,
  satellitePresetMeta,
  type SatellitePresetId,
} from "@/lib/satellitePresets";
import { useAuthStore } from "@/stores/authStore";

function scheduleKindLabel(
  kind: string | null | undefined,
  t: (key: string) => string,
): string {
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

function SatelliteListItem({
  satellite,
  onChanged,
}: {
  satellite: Satellite;
  onChanged: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(satellite.name);
  const renameMut = useMutation({
    mutationFn: () =>
      updateSatellite({
        id: satellite.id,
        revision: satellite.revision + 1,
        name: name.trim(),
        exercise_type: satellite.exercise_type as "B" | "C",
        schedule_kind: (satellite.schedule_kind ?? "daily") as
          | "daily"
          | "weekdays"
          | "category",
        weekdays: satellite.weekdays,
        schedule_category: satellite.schedule_category as
          | "anytime"
          | "post_workout"
          | "rest_day"
          | null
          | undefined,
        active_metrics: satellite.active_metrics,
        equipment: satellite.equipment,
        tags: satellite.tags,
        steps: satellite.steps,
        expected_current_config_version_id: satellite.current_config_version_id,
      }),
    onSuccess: async () => {
      setEditing(false);
      await onChanged();
    },
  });
  const cloneMut = useMutation({
    mutationFn: () =>
      cloneSatellite(satellite.id, {
        name: t("satellites.cloneName", { name: satellite.name }),
      }),
    onSuccess: async () => {
      await onChanged();
    },
  });

  return (
    <li className="rounded-xl border border-slate-200 bg-white/80 px-4 py-3 text-sm">
      {editing ? (
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (!name.trim()) return;
            renameMut.mutate();
          }}
        >
          <Input
            label={t("satellites.name")}
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          {renameMut.isError ? (
            <p className="text-sm text-rose-700">
              {renameMut.error instanceof ApiError
                ? t(errorCodeToI18nKey(renameMut.error.errorCode))
                : t("errors.generic")}
            </p>
          ) : null}
          <div className="flex gap-2">
            <Button type="submit" disabled={renameMut.isPending || !name.trim()}>
              {t("satellites.saveEdit")}
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setName(satellite.name);
                setEditing(false);
              }}
            >
              {t("satellites.cancelEdit")}
            </Button>
          </div>
        </form>
      ) : (
        <>
          <div className="flex items-start justify-between gap-2">
            <p className="font-medium">{satellite.name}</p>
            <div className="flex gap-1">
              <Button type="button" variant="ghost" onClick={() => setEditing(true)}>
                {t("satellites.edit")}
              </Button>
              <Button
                type="button"
                variant="ghost"
                disabled={cloneMut.isPending}
                onClick={() => cloneMut.mutate()}
              >
                {t("satellites.clone")}
              </Button>
            </div>
          </div>
          <p className="text-xs text-slate-500">
            {scheduleKindLabel(satellite.schedule_kind, t)} ·{" "}
            {t("satellites.steps", { n: satellite.steps.length })} ·{" "}
            {satellite.exercise_type}
          </p>
          {satellite.config_status === "pending" && satellite.config_effective_on ? (
            <p className="mt-1 text-xs text-amber-800">
              {t("satellites.pendingFrom", {
                date: satellite.config_effective_on,
              })}
            </p>
          ) : null}
          {cloneMut.isError ? (
            <p className="mt-1 text-sm text-rose-700">
              {cloneMut.error instanceof ApiError
                ? t(errorCodeToI18nKey(cloneMut.error.errorCode))
                : t("errors.generic")}
            </p>
          ) : null}
        </>
      )}
    </li>
  );
}

export function SatellitesPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const me = useAuthStore((s) => s.me);
  const [name, setName] = useState("");
  const [exerciseType, setExerciseType] = useState<"B" | "C">("B");
  const [goalSets, setGoalSets] = useState(3);
  const [goalReps, setGoalReps] = useState(10);
  const [requireBothSides, setRequireBothSides] = useState(false);
  const [trackWeight, setTrackWeight] = useState(false);

  const listQ = useQuery({
    queryKey: ["satellites"],
    queryFn: listSatellites,
  });

  const createMut = useMutation({
    mutationFn: () => {
      if (!me?.id) throw new ApiError(401, "unauthorized");
      return createSatelliteOfflineAware(me.id, {
        name,
        exercise_type: exerciseType,
        schedule_kind: "daily",
        goalSets: exerciseType === "B" ? goalSets : undefined,
        goalReps: exerciseType === "B" ? goalReps : undefined,
        requireBothSides: exerciseType === "B" ? requireBothSides : false,
        trackWeight: exerciseType === "B" ? trackWeight : false,
        stepName: t("satellites.defaultStepName"),
      });
    },
    onSuccess: async () => {
      setName("");
      await qc.invalidateQueries({ queryKey: ["satellites"] });
      await qc.invalidateQueries({ queryKey: ["today"] });
    },
  });

  const presetMut = useMutation({
    mutationFn: (presetId: SatellitePresetId) => {
      if (!me?.id) throw new ApiError(401, "unauthorized");
      return createSatellitePresetOfflineAware(me.id, presetId);
    },
    onSuccess: async () => {
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
            <SatelliteListItem
              key={s.id}
              satellite={s}
              onChanged={async () => {
                await qc.invalidateQueries({ queryKey: ["satellites"] });
                await qc.invalidateQueries({ queryKey: ["today"] });
              }}
            />
          ))}
        </ul>

        <section className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white/70 p-4">
          <h2 className="font-display text-lg font-semibold">
            {t("satellites.presetsTitle")}
          </h2>
          <p className="text-sm text-slate-600">{t("satellites.presetsHint")}</p>
          <ul className="flex flex-col gap-2">
            {SATELLITE_PRESET_IDS.map((presetId) => {
              const meta = satellitePresetMeta(presetId);
              return (
                <li
                  key={presetId}
                  className="flex flex-col gap-2 border-t border-slate-100 pt-3 first:border-t-0 first:pt-0 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div>
                    <p className="font-medium">{meta.defaultName}</p>
                    <p className="text-xs text-slate-500">{t(meta.summaryKey)}</p>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={presetMut.isPending || count >= 10}
                    onClick={() => presetMut.mutate(presetId)}
                  >
                    {t("satellites.addPreset")}
                  </Button>
                </li>
              );
            })}
          </ul>
          {presetMut.isError ? (
            <p className="text-sm text-rose-700">
              {presetMut.error instanceof ApiError
                ? t(errorCodeToI18nKey(presetMut.error.errorCode))
                : t("errors.generic")}
            </p>
          ) : null}
        </section>

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
            label={t("satellites.exerciseType")}
            value={exerciseType}
            onChange={(e) => setExerciseType(e.target.value as "B" | "C")}
          >
            <option value="B">{t("satellites.typeB")}</option>
            <option value="C">{t("satellites.typeC")}</option>
          </Select>
          {exerciseType === "B" ? (
            <>
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
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={requireBothSides}
                  onChange={(e) => setRequireBothSides(e.target.checked)}
                />
                {t("satellites.requireBothSides")}
              </label>
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={trackWeight}
                  onChange={(e) => setTrackWeight(e.target.checked)}
                />
                {t("satellites.trackWeight")}
              </label>
            </>
          ) : (
            <p className="text-sm text-slate-600">{t("satellites.typeCHint")}</p>
          )}
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
