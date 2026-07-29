import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { Button, Input, Page } from "@/components/ui";
import { SyncStatusBanner } from "@/features/sync/SyncStatusBanner";
import { createMeasurementOfflineAware } from "@/features/sync/writes";
import { listMeasurements } from "@/features/training/api";
import { ApiError } from "@/lib/api";
import { formatDateInTimezone } from "@/lib/dates";
import { errorCodeToI18nKey } from "@/lib/errors";
import { useAuthStore } from "@/stores/authStore";

export function MeasurementsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const me = useAuthStore((s) => s.me);
  const [weight, setWeight] = useState("");
  const [waist, setWaist] = useState("");
  const [biceps, setBiceps] = useState("");

  const listQ = useQuery({
    queryKey: ["measurements"],
    queryFn: listMeasurements,
  });

  const createMut = useMutation({
    mutationFn: () => {
      if (!me?.id) throw new ApiError(401, "unauthorized");
      const now = new Date();
      const tz = me.timezone ?? "Europe/Warsaw";
      return createMeasurementOfflineAware(me.id, {
        measuredAt: now.toISOString(),
        localDate: formatDateInTimezone(tz, now),
        weightKg: weight ? Number(weight) : undefined,
        waistCm: waist ? Number(waist) : undefined,
        bicepsCm: biceps ? Number(biceps) : undefined,
      });
    },
    onSuccess: async () => {
      setWeight("");
      setWaist("");
      setBiceps("");
      await qc.invalidateQueries({ queryKey: ["measurements"] });
    },
  });

  return (
    <>
      <SyncStatusBanner />
      <Page title={t("measurements.title")}>
      {listQ.isLoading ? <p>{t("shell.loading")}</p> : null}
      <ul className="flex flex-col gap-2">
        {(listQ.data ?? []).map((m) => {
          const metrics = m.metrics as Record<string, unknown>;
          return (
            <li
              key={m.id}
              className="rounded-xl border border-slate-200 bg-white/80 px-4 py-3 text-sm"
            >
              <p className="font-medium">{m.local_date}</p>
              <p className="text-slate-600">
                {[
                  metrics.weight_kg != null
                    ? t("measurements.weightValue", { value: metrics.weight_kg })
                    : null,
                  metrics.waist_cm != null
                    ? t("measurements.cmValue", { value: metrics.waist_cm })
                    : null,
                  metrics.biceps_cm != null
                    ? t("measurements.cmValue", { value: metrics.biceps_cm })
                    : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </li>
          );
        })}
      </ul>

      <form
        className="flex flex-col gap-3 rounded-xl border border-dashed border-slate-300 bg-white/60 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          createMut.mutate();
        }}
      >
        <h2 className="font-display text-lg font-semibold">{t("measurements.add")}</h2>
        <Input
          label={t("measurements.weight")}
          type="number"
          step="0.1"
          value={weight}
          onChange={(e) => setWeight(e.target.value)}
        />
        <Input
          label={t("measurements.waist")}
          type="number"
          step="0.1"
          value={waist}
          onChange={(e) => setWaist(e.target.value)}
        />
        <Input
          label={t("measurements.biceps")}
          type="number"
          step="0.1"
          value={biceps}
          onChange={(e) => setBiceps(e.target.value)}
        />
        {createMut.isError ? (
          <p className="text-sm text-rose-700">
            {createMut.error instanceof ApiError
              ? t(errorCodeToI18nKey(createMut.error.errorCode))
              : t("errors.generic")}
          </p>
        ) : null}
        <Button type="submit" disabled={createMut.isPending}>
          {t("measurements.submit")}
        </Button>
      </form>
    </Page>
    </>
  );
}
