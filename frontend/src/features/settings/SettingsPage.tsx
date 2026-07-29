import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { Button, Input, Page, Select } from "@/components/ui";
import { logout, logoutAll, patchSchedule } from "@/features/auth/api";
import { syncNow } from "@/features/sync/bootstrap";
import { SyncStatusBanner } from "@/features/sync/SyncStatusBanner";
import { acknowledgeConflict } from "@/lib/db/cache";
import { ApiError } from "@/lib/api";
import { errorCodeToI18nKey } from "@/lib/errors";
import { useAuthStore } from "@/stores/authStore";
import { useSyncStore } from "@/stores/syncStore";

const TIMEZONES = [
  "Europe/Warsaw",
  "Europe/Berlin",
  "Europe/London",
  "UTC",
  "America/New_York",
];

export function SettingsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const me = useAuthStore((s) => s.me);
  const clear = useAuthStore((s) => s.clear);
  const resetSync = useSyncStore((s) => s.reset);
  const qc = useQueryClient();
  const pending = useSyncStore((s) => s.pending);
  const quarantine = useSyncStore((s) => s.quarantine);
  const persisted = useSyncStore((s) => s.persisted);
  const oldestPendingAt = useSyncStore((s) => s.oldestPendingAt);
  const conflicts = useSyncStore((s) => s.conflicts);
  const refresh = useSyncStore((s) => s.refresh);
  const [tz, setTz] = useState(me?.timezone ?? "Europe/Warsaw");
  const [anchor, setAnchor] = useState<"1" | "2" | "">("");
  const [scheduleMsg, setScheduleMsg] = useState<string | null>(null);

  const logoutMut = useMutation({
    mutationFn: logout,
    onSuccess: async () => {
      clear();
      resetSync();
      await qc.clear();
      navigate("/login", { replace: true });
    },
  });

  const logoutAllMut = useMutation({
    mutationFn: logoutAll,
    onSuccess: async () => {
      clear();
      resetSync();
      await qc.clear();
      navigate("/login", { replace: true });
    },
  });

  const scheduleMut = useMutation({
    mutationFn: async () => {
      if (me?.id && navigator.onLine) {
        await syncNow(me.id, me.locale);
      }
      const body: {
        pending_timezone?: string;
        pending_anchor_weekday?: 1 | 2;
      } = {};
      if (tz && tz !== me?.timezone) body.pending_timezone = tz;
      if (anchor === "1" || anchor === "2") {
        body.pending_anchor_weekday = Number(anchor) as 1 | 2;
      }
      if (!body.pending_timezone && body.pending_anchor_weekday == null) {
        throw new ApiError(422, "nothing_to_update");
      }
      return patchSchedule(body);
    },
    onSuccess: (res) => {
      const on =
        res.timezone_effective_on ?? res.schedule_effective_on ?? null;
      setScheduleMsg(
        on ? t("settings.schedulePending", { date: String(on) }) : t("settings.scheduleSaved"),
      );
    },
  });

  return (
    <>
      <SyncStatusBanner />
      <Page title={t("settings.title")}>
        <div className="rounded-xl border border-slate-200 bg-white/80 px-4 py-3 text-sm">
          <p className="font-medium">{me?.display_name || me?.email || t("settings.user")}</p>
          <p className="text-slate-500">{me?.email}</p>
          <p className="text-slate-500">
            {me?.locale} · {me?.timezone}
          </p>
        </div>

        <section className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white/80 p-4">
          <h2 className="font-display text-lg font-semibold">{t("settings.syncTitle")}</h2>
          <p className="text-sm text-slate-600">
            {t("settings.syncPending", { pending, quarantine })}
          </p>
          <p className="text-sm text-slate-600">
            {persisted === true
              ? t("settings.persistOk")
              : persisted === false
                ? t("settings.persistNo")
                : t("settings.persistUnknown")}
          </p>
          {oldestPendingAt ? (
            <p className="text-xs text-slate-500">
              {t("settings.oldestPending", { at: oldestPendingAt })}
            </p>
          ) : null}
          <Button
            variant="secondary"
            disabled={!me?.id || !navigator.onLine}
            onClick={() => me?.id && void syncNow(me.id, me.locale)}
          >
            {t("sync.syncNow")}
          </Button>
          {conflicts.filter((c) => !c.acknowledged).length > 0 ? (
            <ul className="flex flex-col gap-2 text-sm">
              <li className="font-medium">{t("settings.conflicts")}</li>
              {conflicts
                .filter((c) => !c.acknowledged)
                .map((c) => (
                  <li
                    key={c.id}
                    className="flex items-center justify-between gap-2 rounded-lg bg-violet-50 px-3 py-2"
                  >
                    <span>
                      {c.conflict_kind} · {c.entity_type}
                    </span>
                    <Button
                      variant="ghost"
                      onClick={() => {
                        if (!me?.id) return;
                        void acknowledgeConflict(me.id, c.id).then(() => refresh());
                      }}
                    >
                      {t("common.close")}
                    </Button>
                  </li>
                ))}
            </ul>
          ) : null}
        </section>

        <section className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white/80 p-4">
          <h2 className="font-display text-lg font-semibold">{t("settings.scheduleTitle")}</h2>
          <p className="text-sm text-slate-600">{t("settings.scheduleHint")}</p>
          <Select
            label={t("settings.split")}
            value={anchor}
            onChange={(e) => setAnchor(e.target.value as "1" | "2" | "")}
          >
            <option value="">{t("settings.splitUnchanged")}</option>
            <option value="1">{t("onboarding.splitMon")}</option>
            <option value="2">{t("onboarding.splitTue")}</option>
          </Select>
          <Select
            label={t("settings.timezone")}
            value={tz}
            onChange={(e) => setTz(e.target.value)}
          >
            {TIMEZONES.map((z) => (
              <option key={z} value={z}>
                {z}
              </option>
            ))}
          </Select>
          <Input
            label={t("settings.timezoneCustom")}
            value={tz}
            onChange={(e) => setTz(e.target.value)}
          />
          {scheduleMsg ? <p className="text-sm text-teal-800">{scheduleMsg}</p> : null}
          {scheduleMut.isError ? (
            <p className="text-sm text-rose-700">
              {scheduleMut.error instanceof ApiError
                ? t(errorCodeToI18nKey(scheduleMut.error.errorCode))
                : t("errors.generic")}
            </p>
          ) : null}
          <Button
            disabled={scheduleMut.isPending || !me}
            onClick={() => scheduleMut.mutate()}
          >
            {t("settings.saveSchedule")}
          </Button>
        </section>

        <div className="flex flex-col gap-2">
          <Button
            variant="secondary"
            disabled={logoutMut.isPending}
            onClick={() => logoutMut.mutate()}
          >
            {t("settings.logout")}
          </Button>
          <Button
            variant="danger"
            disabled={logoutAllMut.isPending}
            onClick={() => logoutAllMut.mutate()}
          >
            {t("settings.logoutAll")}
          </Button>
        </div>
      </Page>
    </>
  );
}
