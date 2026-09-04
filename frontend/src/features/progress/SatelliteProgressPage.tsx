import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useSearchParams } from "react-router-dom";

import { Page } from "@/components/ui";
import {
  scheduleLabelKey,
  weekdayLabelKeys,
} from "@/features/progress/satelliteSchedule";
import { listSatelliteProgressCached } from "@/features/progress/satelliteProgressCache";
import { ApiError } from "@/lib/api";
import { errorCodeToI18nKey } from "@/lib/errors";
import type { SatelliteProgressItem } from "@/lib/schemas";
import { useAuthStore } from "@/stores/authStore";

function ScheduleLine({ item }: { item: SatelliteProgressItem }) {
  const { t } = useTranslation();
  const label = scheduleLabelKey(item);
  if (label.weekdays) {
    const days = weekdayLabelKeys(label.weekdays)
      .map((k) => t(k))
      .join("/");
    return <span>{days}</span>;
  }
  return <span>{t(label.key)}</span>;
}

export function SatelliteProgressPage() {
  const { t } = useTranslation();
  const [searchParams] = useSearchParams();
  const userId = useAuthStore((s) => s.me?.id);
  const adjustId = searchParams.get("adjust");
  const relatedOutcomeId = searchParams.get("relatedOutcome");

  const listQ = useQuery({
    queryKey: ["satellite-progress"],
    queryFn: () => listSatelliteProgressCached(userId!),
    enabled: !!userId,
  });

  const { typeB, typeC } = useMemo(() => {
    const items = listQ.data ?? [];
    return {
      typeB: items.filter((i) => i.exercise_type === "B"),
      typeC: items.filter((i) => i.exercise_type === "C"),
    };
  }, [listQ.data]);

  if (adjustId) {
    const qs = new URLSearchParams({ adjust: adjustId });
    if (relatedOutcomeId) qs.set("relatedOutcome", relatedOutcomeId);
    return (
      <Navigate to={`/sat-progress/${adjustId}?${qs.toString()}`} replace />
    );
  }

  if (listQ.isLoading) {
    return <Page title={t("satProgress.title")}>{t("shell.loading")}</Page>;
  }
  if (listQ.isError) {
    const code =
      listQ.error instanceof ApiError ? listQ.error.errorCode : "generic";
    return (
      <Page title={t("satProgress.title")}>
        <p className="text-rose-700">{t(errorCodeToI18nKey(code))}</p>
      </Page>
    );
  }

  const empty = typeB.length === 0 && typeC.length === 0;

  return (
    <Page title={t("satProgress.title")}>
      <p className="text-sm text-slate-600">{t("satProgress.hint")}</p>

      {empty ? (
        <p className="rounded-xl border border-dashed border-slate-300 bg-white/60 px-4 py-6 text-sm text-slate-600">
          {t("satProgress.empty")}{" "}
          <Link className="font-medium text-teal-800 underline" to="/satellites">
            {t("satProgress.emptyLink")}
          </Link>
        </p>
      ) : null}

      {typeB.length > 0 ? (
        <section className="flex flex-col gap-3" aria-labelledby="sat-b-heading">
          <h2 id="sat-b-heading" className="font-display text-lg font-semibold">
            {t("satProgress.sectionB")}
          </h2>
          <ul className="flex flex-col gap-2">
            {typeB.map((item) => (
              <li key={item.id}>
                <Link
                  to={`/sat-progress/${item.id}`}
                  className="block rounded-xl border border-slate-200 bg-white/80 px-4 py-3 hover:border-teal-300"
                >
                  <p className="font-medium text-slate-900">{item.name}</p>
                  <p className="text-xs text-slate-500">
                    <ScheduleLine item={item} />
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {typeC.length > 0 ? (
        <section className="flex flex-col gap-3" aria-labelledby="sat-c-heading">
          <h2 id="sat-c-heading" className="font-display text-lg font-semibold">
            {t("satProgress.sectionC")}
          </h2>
          <ul className="flex flex-col gap-2">
            {typeC.map((item) => (
              <li key={item.id}>
                <Link
                  to={`/sat-progress/${item.id}`}
                  className="block rounded-xl border border-slate-200 bg-white/80 px-4 py-3 hover:border-teal-300"
                >
                  <p className="font-medium text-slate-900">{item.name}</p>
                  <p className="text-xs text-slate-500">
                    <ScheduleLine item={item} />
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </Page>
  );
}
