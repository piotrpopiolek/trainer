import { useMemo, useState, type ChangeEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { Button, Input, Page } from "@/components/ui";
import { MeasurementTrendsSection } from "@/features/measurements/MeasurementTrendsSection";
import { SyncStatusBanner } from "@/features/sync/SyncStatusBanner";
import { createMeasurementOfflineAware } from "@/features/sync/writes";
import { listMeasurements } from "@/features/training/api";
import { ApiError } from "@/lib/api";
import { formatDateInTimezone } from "@/lib/dates";
import { errorCodeToI18nKey } from "@/lib/errors";
import { useAuthStore } from "@/stores/authStore";

/** FR-061 default + optional circumference keys (API: BodyMetricsV1). */
const DEFAULT_FIELDS = [
  { key: "weight_kg", i18n: "measurements.weight", step: "0.1" },
  { key: "waist_cm", i18n: "measurements.waist", step: "0.1" },
  { key: "biceps_cm", i18n: "measurements.biceps", step: "0.1" },
] as const;

const OPTIONAL_FIELDS = [
  { key: "chest_cm", i18n: "measurements.chest", step: "0.1" },
  { key: "thigh_cm", i18n: "measurements.thigh", step: "0.1" },
  { key: "neck_cm", i18n: "measurements.neck", step: "0.1" },
  { key: "abdomen_cm", i18n: "measurements.abdomen", step: "0.1" },
  { key: "hips_cm", i18n: "measurements.hips", step: "0.1" },
  { key: "calves_cm", i18n: "measurements.calf", step: "0.1" },
] as const;

const ALL_FIELDS = [...DEFAULT_FIELDS, ...OPTIONAL_FIELDS];

type MetricKey = (typeof ALL_FIELDS)[number]["key"];

function emptyValues(): Record<MetricKey, string> {
  return Object.fromEntries(ALL_FIELDS.map((f) => [f.key, ""])) as Record<
    MetricKey,
    string
  >;
}

function formatMetricLine(
  key: string,
  value: unknown,
  t: (k: string, opts?: Record<string, unknown>) => string,
): string | null {
  if (value == null || value === "") return null;
  if (key === "weight_kg") {
    return t("measurements.weightValue", { value });
  }
  const labelKey =
    ALL_FIELDS.find((f) => f.key === key)?.i18n ??
    (key === "calf_cm" ? "measurements.calf" : null);
  if (!labelKey) {
    return `${key}: ${t("measurements.cmValue", { value })}`;
  }
  const short = t(labelKey).replace(/\s*\(.*\)$/, "");
  return `${short} ${t("measurements.cmValue", { value })}`;
}

export function MeasurementsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const me = useAuthStore((s) => s.me);
  const [values, setValues] = useState(emptyValues);
  const [notes, setNotes] = useState("");

  const tz = me?.timezone ?? "Europe/Warsaw";
  const todayLocalDate = formatDateInTimezone(tz, new Date());

  const listQ = useQuery({
    queryKey: ["measurements"],
    queryFn: listMeasurements,
  });

  const createMut = useMutation({
    mutationFn: () => {
      if (!me?.id) throw new ApiError(401, "unauthorized");
      const now = new Date();
      const num = (k: MetricKey) => {
        const raw = values[k].trim();
        if (!raw) return undefined;
        const n = Number(raw);
        return Number.isFinite(n) ? n : undefined;
      };
      return createMeasurementOfflineAware(me.id, {
        measuredAt: now.toISOString(),
        localDate: formatDateInTimezone(tz, now),
        weightKg: num("weight_kg"),
        waistCm: num("waist_cm"),
        bicepsCm: num("biceps_cm"),
        chestCm: num("chest_cm"),
        thighCm: num("thigh_cm"),
        neckCm: num("neck_cm"),
        abdomenCm: num("abdomen_cm"),
        hipsCm: num("hips_cm"),
        calvesCm: num("calves_cm"),
        notes: notes.trim() || undefined,
      });
    },
    onSuccess: async () => {
      setValues(emptyValues());
      setNotes("");
      await qc.invalidateQueries({ queryKey: ["measurements"] });
    },
  });

  const fieldSetter = useMemo(
    () => (key: MetricKey) => (e: ChangeEvent<HTMLInputElement>) => {
      setValues((prev) => ({ ...prev, [key]: e.target.value }));
    },
    [],
  );

  return (
    <>
      <SyncStatusBanner />
      <Page title={t("measurements.title")}>
        {listQ.isLoading ? <p>{t("shell.loading")}</p> : null}

        {!listQ.isLoading ? (
          <MeasurementTrendsSection
            items={listQ.data ?? []}
            todayLocalDate={todayLocalDate}
          />
        ) : null}

        <form
          className="flex flex-col gap-3 rounded-xl border border-dashed border-slate-300 bg-white/60 p-4"
          onSubmit={(e) => {
            e.preventDefault();
            createMut.mutate();
          }}
        >
          <h2 className="font-display text-lg font-semibold">{t("measurements.add")}</h2>
          <p className="text-xs text-slate-500">{t("measurements.defaultsHint")}</p>
          {DEFAULT_FIELDS.map((f) => (
            <Input
              key={f.key}
              label={t(f.i18n)}
              type="number"
              step={f.step}
              min={0}
              value={values[f.key]}
              onChange={fieldSetter(f.key)}
            />
          ))}
          <p className="pt-1 text-xs font-medium text-slate-600">
            {t("measurements.optionalHint")}
          </p>
          {OPTIONAL_FIELDS.map((f) => (
            <Input
              key={f.key}
              label={t(f.i18n)}
              type="number"
              step={f.step}
              min={0}
              value={values[f.key]}
              onChange={fieldSetter(f.key)}
            />
          ))}
          <Input
            label={t("measurements.notes")}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
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

        <ul className="flex flex-col gap-2">
          {(listQ.data ?? []).map((m) => {
            const metrics = m.metrics as Record<string, unknown>;
            const lines = Object.entries(metrics)
              .filter(([k]) => k !== "schema_version")
              .map(([k, v]) => formatMetricLine(k, v, t))
              .filter(Boolean);
            return (
              <li
                key={m.id}
                className="rounded-xl border border-slate-200 bg-white/80 px-4 py-3 text-sm"
              >
                <p className="font-medium">{m.local_date}</p>
                <p className="text-slate-600">{lines.join(" · ")}</p>
                {m.notes ? <p className="mt-1 text-slate-500">{m.notes}</p> : null}
              </li>
            );
          })}
        </ul>
      </Page>
    </>
  );
}
